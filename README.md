# Server setup

Here is the server setup / hardening process for Ubuntu:

1. After first login with the root user, first things first, lets make sure everything is updated:
```
apt update
apt upgrade
```
2. Reboot if necessary (eg. by using the `reboot` command).
3. Login back to the server as root, and change the root user password:
```
passwd
```
4. Enter new password (make sure to save it somewhere secure!)
5. We don't want to use root for day to day tasks so we add a less privileged user aptly named `user`:
```
adduser user
```
We enter (and securely store!) the user's password. Other requested info can be left blank.

6. We want to give `sudo` privileges for the `user` we created so that they can perform admin tasks when needed:
```
usermod -aG sudo user
```
7. Now we type `exit` and login with our `user` account (123... being server IP address):
```
ssh user@123.123.123.123 
```
8. When requested we enter the `user`'s password we created above.

From now on, when logged in as `user`, we can use `sudo` in front of commands that require elevated privileges (when getting Permission Denied otherwise, for instance).

10. It is also a good idea to disable `root` ssh capability entirely at this point. For that, we need to edit a config file for `ssh`:
```
sudo nano /etc/ssh/sshd_config
```
11. From there we scroll down a bit and find `PermitRootLogin`, remove the `#` in front of it if it exists then change the line to:
```
PermitRootLogin no
```
The sky is the limit with hardening but since this server just serves static content with no user data at risk, this should be enough. We'll configure a firewall when we set up the application.

# Application setup

1. After connecting as `user` let's go to home folder:
```
cd /home/user
```
2. First we need to get the .torrent file for the website .zim archive. (source is [here](https://archive.org/details/www.cdc.gov_en_all_novid_2025-01))
```
wget https://archive.org/download/www.cdc.gov_en_all_novid_2025-01/www.cdc.gov_en_all_novid_2025-01_archive.torrent
```
3. Then we need to download the torrented files, which might take some time (it is a 100GB archive). First let's download a torrent client called `transmission-cli`
```
sudo apt-get install transmission-cli
```
4. Then let's download the torrented archive (`-w .` means output folder is this folder):
```
transmission-cli ./www.cdc.gov_en_all_novid_2025-01_archive.torrent -w .
```
Wait for the download to finish. Among the downloaded files, there is this huge archive with .zim extension which we will need later. 
We also need to be able to pull the private github repo. For that, we need to setup a deploy key in github. 

5. First let's create an ssh key:
```
ssh-keygen -t ed25519 -C "cdc-mirror-github-deploy-key"
```
We don't need a password, leave blank when prompted. 

6. Then we need to get the public key by running:
```
cat ~/.ssh/cdc-mirror-github-deploy-key.pub
```
7. The public key will be printed. Copy this public key, then go to the repo in github.com, under Settings -> Deploy Keys add this public key.

8. To be able to use this key on the system create a file named `config` under `~/.ssh/` with the contents:
```
Host github.com
	IdentityFile ~/.ssh/cdc-mirror-github-deploy-key
	AddKeysToAgent yes
```
9. Now we should be able to pull the repository:
```
git clone git@github.com:RestoredCDC/CDC_zim_mirror.git 
```
10. Now move that file with the .zim extension to the repo folder (where zim_converter.py lives; modify the paths before running this).
```
mv www.cdc.gov_en_all_novid_2025-01/www.cdc.gov_en_all_novid_2025-01.zim ./CDC_zim_mirror/ 
```
That is all we need regarding data. Now let's create a virtual python environment.

# Python Virtual Environment

1. Navigate to the zim directory
```
cd CDC_zim_mirror
```
2. Install using apt the python virtual environment package (might be needed first depending on system) and create the environment.
```
sudo apt install python3.12-venv
python3 -m venv venv
```
3. Activate the environment:
```
source ./venv/bin/activate
```
Now there should be a (venv) prefix at the beginning of our terminal prompt.

4. We need to install the requirements
```
pip install -r requirements.txt
```
(if you are on Windows for testing, you might need to change `plyvel` package in the `requirements.txt` file to `plyvel-ci`)

## Convert zim file
If all goes right, we can now convert our .zim file to a LevelDB database (will be stored under `./cdc_database`)

1. Run the zim converter script
```
python ./zim_converter.py
```
This will take some time, progress will be printed on screen. There might be some additional printing in between progress for redirects and errors. You will get a list of all paths that reported an error at the end. The listed `['Counter', 'Creator', 'Date', 'Description', 'Illustration_48x48@1', 'Language', 'Name', 'Publisher', 'Scraper', 'Source', 'Tags', 'Title', 'X-ContentDate', 'mainPage', 'fulltext/xapian', 'listing/titleOrdered/v0', 'listing/titleOrdered/v1', 'title/xapian']` paths as errors at the end are not important for our purposes.

If the process ends before printing "done" maybe the server does not have enough RAM. In that case you will need to enable swap in linux to compensate which I won't go into here but mentioning it here as a pointer.

Also beware that the .zim file is around 100GB. The generated LevelDB database will be around 95GB. So to do this conversion in server, you need about 200GB free space for this to succeed.

2. After the conversion is done, you may delete the .zim file to save space since everything is included in the LevelDB database residing in `./cdc_database`
```
rm ./www.cdc.gov_en_all_novid_2025-01.zim
```
3. At this point, serving the mirror is possible by just running:
```
python ./serve.py
```
This will serve the page at port 9090. Since we don't yet have a firewall setup, the website should be accessible at `http://server ip address:9090/`

At this stage, if you close your ssh session, since the process is tied to the session the server will terminate. 

4. If you want the server to keep running after you terminate the ssh session, run it like the following:
```
nohup python ./serve.py > /dev/null 2>&1 &
```
(`> /dev/null 2>&1 &` part means we are ignoring all console output, sending them to the blackhole that is `/dev/null` - when you want to store them in a file, change the `/dev/null/` path.)

5. When you login later, if you want to stop the server you can use `sudo pkill -f serve.py` in a pinch.

Next we need setup things in a way that is robust for serving to the world.

# Setting up auto-start and auto-restart

Once the server is confirmed to be running properly as described above, we should set things up in a way so that the process starts at each boot, and restarts automatically if it crashes.

A common way to do this in Ubuntu (and other related distros) is using the `systemd` service.

Let's create a service file that will achieve what we want.

1. Create the file `/etc/systemd/system/cdcmirror.service` (with `sudo` privileges) with the following contents:

```
[Unit]
Description=CDC Mirror Server Process
After=network.target

[Service]
User=server_user
WorkingDirectory=/home/server_user/CDC_zim_mirror
Environment="PATH=/home/server_user/CDC_zim_mirror/venv/bin"
ExecStart=/home/server_user/CDC_zim_mirror/venv/bin/python serve.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

This will run our serve.py process in the right python environment under `server_user` account. Change the `server_user` to the name of the user dedicated to running this process (create the user if necessary) and also the `WorkingDirectory`, `Environment` and `ExecStart` paths if your paths differ.

2. After creating this file, you need to reload the systemd daemon:
```
sudo systemctl daemon-reload
```
3. To start the service run:
```
sudo systemctl start cdcmirror.service
```
4. And to make it run automatically on startup (or after a reboot):
```
sudo systemctl enable cdcmirror.service
```
5. Restart the server by:
```
sudo systemctl restart cdcmirror.service
```
# Pulling in changes with git

Login as `user` or whichever user you use for deployment. Go to the repo folder where the server is hosted from and do a `git pull`. Then restart the server using `sudo systemctl restart cdcmirror.service` command described above.

# Configuring server settings

The `serve.py` file (which serves the entire website) is very short, simple, and well commented. You may change the value of the `serverPort` variable at the top to make the script serve from a different port. You can also change the HTML string inside the `DISCLAIMER_HTML` variable to change the disclaimer that is injected in each page. This snippet is inserted directly after the `body` tag (right after it is opened) of the HTML in each page.

...to be continued

## Server setup

Here is the server setup / hardening process for Ubuntu:

After first login with the root user, first things first, lets make sure everything is updated:

`apt update`

`apt upgrade`

Reboot if necessary (eg. by using the `reboot` command).

Login back to the server as root, and change the root user password:

`passwd`

Enter new password (make sure to save it somewhere secure!)

We don't want to use root for day to day tasks so we add a less privileged user aptly named `user`:

`adduser user`

We enter (and securely store!) the user's password. Other requested info can be left blank.

We want to give `sudo` privileges for the `user` we created so that they can perform admin tasks when needed:

`usermod -aG sudo user`

Now we type `exit` and login with our `user` account:

`ssh user@123.123.123.123` (123... being server IP address)

When requested we enter the `user`'s password we created above.

From now on, when logged in as `user`, we can use `sudo` in front of commands that require elevated privileges (when getting Permission Denied otherwise, for instance).

It is also a good idea to disable `root` ssh capability entirely at this point. For that, we need to edit a config file for `ssh`:

`sudo nano /etc/ssh/sshd_config`

From there we scroll down a bit and find `PermitRootLogin`, remove the `#` in front of it if it exists then change the line to:

`PermitRootLogin no`

The sky is the limit with hardening but since this server just serves static content with no user data at risk, this should be enough. We'll configure a firewall when we set up the application.

## Application setup

After connecting as `user` let's go to home folder:

`cd /home/user`

First we need to get the .torrent file for the website .zim archive. (source is https://archive.org/details/www.cdc.gov_en_all_novid_2025-01 )

`wget https://archive.org/download/www.cdc.gov_en_all_novid_2025-01/www.cdc.gov_en_all_novid_2025-01_archive.torrent`

Then we need to download the torrented files, which might take some time (it is a 100GB archive). First let's download a torrent client called `transmission-cli`

`sudo apt-get install transmission-cli`

Then let's download the torrented archive (`-w .` means output folder is this folder):

`transmission-cli ./www.cdc.gov_en_all_novid_2025-01_archive.torrent -w .`

Wait for the download to finish. Among the downloaded files, there is this huge archive with .zim extension. Move that file with the .zim extension to this folder (where zim_converter.py) lives.

`mv path/to/www.cdc.gov_en_all_novid_2025-01.zim path/to/here` (modify the paths before running this)

That is all we need regarding data. Now let's create a virtual python environment:

`python -m venv venv`

...and then activate the environment:

`source ./venv/bin/activate`

Now there should be a (venv) prefix at the beginning of our terminal prompt.

We need to install the requirements:

`pip install -r requirements.txt`

If all goes right, we can now convert our .zim file to a LevelDB database (will be stored under `./cdc_database`)

`python ./zim_converter.py`

This will take some time, progress will be printed on screen. There might be some additional printing in between progress for redirects and errors. You will get a list of all paths that reported an error at the end. For the cdc .zim archive we are using for this project, there is about 30 paths (among ~380000) that are corrupted in the .zim file, that is not a big deal.

If the process ends before printing "done" maybe the server does not have enough RAM. In that case you will need to enable swap in linux to compensate which I won't go into here but mentioning it here as a pointer.

Also beware that the .zim file is around 100GB. The generated LevelDB database will be around 95GB. So to do this conversion in server, you need about 200GB free space for this to succeed.

After the conversion is done, you may delete the .zim file to save space since everything is included in the LevelDB database residing in `./cdc_database`

`rm ./www.cdc.gov_en_all_novid_2025-01.zim`

At this point, serving the mirror is possible by just running:

`python ./serve.py`

This will serve the page at port 9090. Since we don't yet have a firewall setup, the website should be accessible at `http://server ip address:9090/`

Next we need setup things in a way that is robust for serving to the world.

...to be continued
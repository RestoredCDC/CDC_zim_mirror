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

Wait for the download to finish. Among the downloaded files, there is this huge archive with .zim extension.

...to be continued
# Deploying

```
$ docker build -t teltonika-monitor .

# Save
$ docker save -o /Volumes/General/teltonika-monitor.tar.gz teltonika-monitor:latest

# On simone
$ docker load -i /volume1/General/teltonika-monitor.tar.gz
```

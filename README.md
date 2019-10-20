# Teltonika router monitoring ito Postgres

I imagine this is a pretty niche library. I use it alongside my mate3 library 
for monitoring. I've made this public in case it is useful to anyone.

## Use

```
$ python main.py -h
usage: main.py [-h] --host HOST [--user USER] --password PASSWORD
               [--host-key HOST_KEY] [--database-url DATABASE_URL]
               [--hypertables] [--interval INTERVAL] [--quiet] [--debug]

Read available data from a Teltonika router and insert into postgres

optional arguments:
  -h, --help            show this help message and exit
  --host HOST, -H HOST  The host name or IP address of the Mate3
  --user USER, -U USER  The ssh username for the host
  --password PASSWORD, -P PASSWORD
                        The ssh password for thehost
  --host-key HOST_KEY, -K HOST_KEY
                        The SSH host key. Can also be set with HOST_KEY
                        environment variable
  --database-url DATABASE_URL
                        Postgres database URL
  --hypertables         Should we create tables as hypertables? Use only if
                        you are using TimescaleDB
  --interval INTERVAL, -i INTERVAL
                        Polling interval in seconds
  --quiet, -q           Hide status output. Only errors will be shown
  --debug               Show debug logging
```

## Deploying

```
$ docker build -t teltonika-monitor .

# Save
$ docker save -o /Volumes/General/teltonika-monitor.tar.gz teltonika-monitor:latest

# On simone
$ docker load -i /volume1/General/teltonika-monitor.tar.gz
```

import argparse
import base64
import logging
import os
import time
from sys import argv
from typing import Tuple, List

import paramiko
import psycopg2
from paramiko import SSHException

logger = logging.getLogger("teltonika.monitor")

ARGUMENTS = [
    "--connstate",
    "--netstate",
    "--imei",
    "--iccid",
    "--model",
    "--manuf",
    "--serial",
    "--revision",
    "--imsi",
    "--simstate",
    "--pinstate",
    "--signal",
    "--rscp",
    "--ecio",
    "--rsrp",
    "--sinr",
    "--rsrq",
    "--cellid",
    "--operator",
    "--opernum",
    "--conntype",
    "--temp",
    "--network",
    "--serving",
]

FIELD_NAMES = [
    "connstate",
    "netstate",
    "imei",
    "iccid",
    "model",
    "manuf",
    "serial",
    "revision",
    "imsi",
    "simstate",
    "pinstate",
    "signal",
    "rscp",
    "ecio",
    "rsrp",
    "sinr",
    "rsrq",
    "cellid",
    "operator",
    "opernum",
    "conntype",
    "temp",
    "network",
    "serving",
    # executed in separate commands
    "wan0_bsent",
    "wan0_brecv",
    "wan1_bsent",
    "wan1_brecv",
    # 'serving' also populates the following three fields
    "mcc",
    "mnc",
    "freq_band_ind",
]

TABLE_SQL = """CREATE TABLE IF NOT EXISTS teltonika (
    time TIMESTAMPTZ NOT NULL,
    connstate VARCHAR(100),
    netstate  VARCHAR(100),
    imei  VARCHAR(30),
    iccid  VARCHAR(30),
    model VARCHAR(100),
    manuf VARCHAR(100),
    serial VARCHAR(20),
    revision VARCHAR(20),
    imsi VARCHAR(20),
    simstate VARCHAR(20),
    pinstate VARCHAR(20),
    signal INTEGER,
    rscp VARCHAR(100),
    ecio VARCHAR(100),
    rsrp INTEGER,
    sinr FLOAT,
    rsrq FLOAT,
    cellid INTEGER,
    operator VARCHAR(100),
    opernum INTEGER,
    conntype VARCHAR(20),
    temp INT,
    network VARCHAR(200),
    serving VARCHAR(200),
    mcc INT,
    mnc INT,
    freq_band_ind INT,
    wwan0_bsent BIGINT,
    wwan0_brecv BIGINT,
    wwan1_bsent BIGINT,
    wwan1_brecv BIGINT
)"""


def parse_serving(value: str):
    value = value.split(":", 1)[1].strip()
    values = [v.strip('"') for v in value.split(",")]
    values = [(None if v in ("-", "N/A") else v) for v in values]
    mode = values[2]

    fields_by_mode = {
        "GSM": [
            "state",
            "mode",
            "mcc",
            "mnc",
            "lac",
            "cellid",
            "bsic",
            "arfcn",
            "band",
            "rxlev",
            "txp",
            "rla",
            "drx",
            "c1",
            "c2",
            "gprs",
            "tch",
            "ts",
            "ta",
            "maio",
            "hsn",
            "rxlevsub",
            "rxlevfull",
            "rxqualsub",
            "rxqualfull",
            "voicecodec",
        ],
        "WCDMA": [
            "state",
            "mode",
            "mcc",
            "mnc",
            "lac",
            "cellid",
            "uarfcn",
            "psc",
            "rac",
            "rscp",
            "ecio",
            "phych",
            "sf",
            "slot",
            "speech_code",
            "comMod",
        ],
        "LTE": [
            "state",
            "mode",
            "is_tdd",
            "mcc",
            "mnc",
            "cellid",
            "pcid",
            "earfcn",
            "freq_band_ind",
            "ul_bandwidth",
            "dll_bandwidth",
            "tac",
            "rsrp",
            "rsrq",
            "rssi",
            "sinr",
            "srxlev",
        ],
        "TDSCDMA": [
            "state",
            "mode",
            "mcc",
            "mnc",
            "lac",
            "cellid",
            "pfreq",
            "rssi",
            "rscp",
            "ecio",
        ],
    }

    if mode not in fields_by_mode:
        return {}

    values_dict = dict(zip(fields_by_mode[mode], values[1:]))

    if "cellid" in values_dict:
        values_dict["cellid"] = int(values_dict["cellid"], 16)

    return {k: v for k, v in values_dict.items() if k in FIELD_NAMES}


def create_table(conn, hypertables=False):
    with conn.cursor() as curs:
        logger.debug(f"Executing: {TABLE_SQL}")
        curs.execute(TABLE_SQL)

        if hypertables:
            try:
                sql = f"SELECT create_hypertable('teltonika', 'time')"
                logger.debug(f"Executing: {sql}")
                curs.execute(sql)
            except psycopg2.DatabaseError as e:
                if "already a hypertable" in str(e):
                    logger.debug("Table is already a hypertable")
                else:
                    raise


def insert(conn, values):
    key_values = dict(zip(FIELD_NAMES, values))
    key_values.update(**parse_serving(key_values["serving"]))

    with conn.cursor() as curs:
        sql = (
            f"INSERT INTO teltonika "
            f"(time, {', '.join(key_values.keys())}) "
            f"VALUES (NOW(), {', '.join(['%s'] * len(key_values))})"
        )
        args = list(key_values.values())
        logger.debug(f"Executing: {sql}")
        logger.debug(f"SQL args: {args}")
        curs.execute(sql, args)


def run_command(client, command) -> Tuple[List[str], List[str]]:
    logger.debug(f"Executing command: {command}")

    stdin, stdout, stderr = client.exec_command(command, timeout=10)
    stdout = stdout.readlines()
    stderr = stderr.readlines()

    logger.debug(f"STDOUT: {stdout}")
    logger.debug(f"STDERR: {stderr}")

    return [s.strip() for s in stdout], [s.strip() for s in stderr]


def one_loop(args, ssh_conn, pg_client):
    start = time.time()

    command = f"gsmctl {' '.join(ARGUMENTS)}"
    stdout = (
            run_command(ssh_conn, command)[0]
            +
            # These need to be run in their own commands in order to
            # produce reliable data.
            # Gets data use
            run_command(ssh_conn, "gsmctl --bsent wwan0 --brecv wwan0")[0]
            + run_command(ssh_conn, "gsmctl --bsent wwan0.1 --brecv wwan0.1")[0]
    )

    insert(pg_client, values=[s.strip() for s in stdout])

    total = time.time() - start
    sleep_time = args.interval - total
    if sleep_time > 0:
        time.sleep(args.interval - total)


def main():
    parser = argparse.ArgumentParser(
        description="Read available data from a Teltonika router and insert into postgres"
    )

    parser.add_argument(
        "--host",
        "-H",
        dest="host",
        help="The host name or IP address of the Mate3",
        required=True,
    )

    parser.add_argument(
        "--user",
        "-U",
        dest="user",
        help="The ssh username for the host",
        default="root",
    )

    parser.add_argument(
        "--password",
        "-P",
        dest="password",
        help="The ssh password for thehost",
        required=True,
    )

    parser.add_argument(
        "--host-key",
        "-K",
        dest="host_key",
        help="The SSH host key. Can also be set with HOST_KEY environment variable",
    )

    parser.add_argument(
        "--database-url",
        dest="database_url",
        help="Postgres database URL",
        default="postgres://postgres@localhost/postgres",
    )

    parser.add_argument(
        "--hypertables",
        dest="hypertables",
        help="Should we create tables as hypertables? Use only if you are using TimescaleDB",
        action="store_true",
    )

    parser.add_argument(
        "--interval",
        "-i",
        dest="interval",
        default=60,
        help="Polling interval in seconds",
        type=int,
    )

    parser.add_argument(
        "--quiet",
        "-q",
        dest="quiet",
        help="Hide status output. Only errors will be shown",
        action="store_true",
    )

    parser.add_argument(
        "--debug", dest="debug", help="Show debug logging", action="store_true"
    )

    args = parser.parse_args(argv[1:])

    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        level=logging.ERROR,
    )
    root_logger = logging.getLogger()
    teltonika_logger = logging.getLogger("teltonika")

    if args.debug:
        root_logger.setLevel(logging.DEBUG)
    elif args.quiet:
        teltonika_logger.setLevel(logging.ERROR)
    else:
        teltonika_logger.setLevel(logging.INFO)

    key_b64 = args.host_key or os.environ.get("HOST_KEY", None)
    ssh_host_key = paramiko.RSAKey(data=base64.b64decode(key_b64))

    while True:  # Reconnection loop
        try:
            logger.info(f"Connecting to postgres at: {args.database_url}")
            with psycopg2.connect(args.database_url) as pg_client:
                pg_client.autocommit = True
                create_table(pg_client, hypertables=args.hypertables)

                with paramiko.SSHClient() as ssh_conn:
                    logger.info(f"Connecting to SSH server on teltonika router: {args.host}")
                    ssh_conn.get_host_keys().add(args.host, "ssh-rsa", ssh_host_key)
                    ssh_conn.connect(
                        args.host,
                        username=args.user,
                        password=args.password,
                        allow_agent=False,
                        timeout=5,
                    )
                    logger.info(f"Connection successful. Monitoring will now start")

                    while True:
                        one_loop(args=args, pg_client=pg_client, ssh_conn=ssh_conn)

        except SSHException as e:
            logger.error(f"SSH communication error: {e}. Will try to reconnect in {args.interval} seconds")
            time.sleep(args.interval)
        except (psycopg2.DatabaseError, psycopg2.OperationalError) as e:
            logger.error(f"Postgres communication error: {e}. Will try to reconnect in {args.interval} seconds")
            time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Exiting")
            return


if __name__ == "__main__":
    main()

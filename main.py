import argparse
import base64
import logging
import os
import time
from sys import argv

import paramiko
import psycopg2


logger = logging.getLogger("teltonika_monitor")

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

FIELD_NAMES = [s.strip("-") for s in ARGUMENTS] + ["mcc", "mnc", "freq_band_ind"]

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
    freq_band_ind INT
)"""


def parse_serving(value: str):
    value = value.split(":", 1)[1].strip()
    values = [v.strip('"') for v in value.split(",")]
    values = [(None if v == "-" else v) for v in values]
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
        logger.debug(f"Executing: {sql}")
        curs.execute(sql, list(key_values.values()))


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
    mate3_logger = logging.getLogger("mate3")

    if args.debug:
        root_logger.setLevel(logging.DEBUG)
    elif args.quiet:
        mate3_logger.setLevel(logging.ERROR)
    else:
        mate3_logger.setLevel(logging.INFO)

    key_b64 = args.host_key or os.environ.get("HOST_KEY", None)
    key = paramiko.RSAKey(data=base64.b64decode(key_b64))

    logger.info(f"Connecting to postgres at: {args.database_url}")
    with psycopg2.connect(args.database_url) as conn:
        conn.autocommit = True
        create_table(conn, hypertables=args.hypertables)

        with paramiko.SSHClient() as client:
            logger.info(f"Connecting to SSH server on teltonika router: {args.host}")
            client.get_host_keys().add(args.host, "ssh-rsa", key)
            client.connect(
                args.host, username=args.user, password=args.password, allow_agent=False, timeout=5
            )

            while True:
                start = time.time()

                command = f"gsmctl {' '.join(ARGUMENTS)}"
                logger.debug(f"Executing command: {command}")

                stdin, stdout, stderr = client.exec_command(command, timeout=10)
                stdout = stdout.readlines()
                stderr = stderr.readlines()

                logger.debug(f"STDOUT: {stdout}")
                logger.debug(f"STDERR: {stderr}")

                insert(conn, values=[s.strip() for s in stdout])

                total = time.time() - start
                sleep_time = args.interval - total
                if sleep_time > 0:
                    time.sleep(args.interval - total)


if __name__ == "__main__":
    main()

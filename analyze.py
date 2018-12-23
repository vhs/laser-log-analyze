import os
import re
from datetime import datetime, timedelta
from collections import defaultdict
from influxdb import InfluxDBClient



# ex: Wed, 17 Oct 2018 07:33:03 GMT laser:web New event from laser laserShutdown
RE_LINE = re.compile(r'^(?P<time>.* GMT)\s(?P<key>\S+)\s(?P<message>.*)$')

# NB: The payload returned by MMP is not valid JSON  so we must fish this out with a regex
RE_USERID = re.compile(r'userId: (\d+), username: \'(\S+)\'')

def _to_influx_ts(since):
    """
    ### _to_influx_ts(since)
    Converts datetime to default Influx time format: nanoseconds since epoch.
    Rounds up to the nearest second.
    """

    if not isinstance(since, datetime):
        raise ValueError("Expected 'since' to be a datetime object, got {}".format(type(since)))

    if since.tzinfo != pytz.utc:
        raise ValueError("Requires timezone objects to be UTC, got {}".format(since.tzinfo))

    return int(since.timestamp() + 1) * 1000000000


def parse_line(line):
    r = RE_LINE.match(line)
    parts = r.groupdict()
    if r:
        return (
            datetime.strptime(parts['time'], '%a, %d %b %Y %H:%M:%S %Z'),
            parts['key'],
            parts['message'],
        )

def handle_mmp(line):
    evt = parse_line(line)
    if evt[1] != 'laser:mmp':
        raise ValueError('Not a laser:mmp event')

    r = RE_USERID.search(evt[2])
    if r:
        return r.group(1), r.group(2)

    return None, None

def handle_laser_control(line):
    if evt[1] != 'laser:control':
        raise ValueError('Not a laser:control event')



class LaserInflux(object):
    def __init__(self):
        self.client = InfluxDBClient(
            'stats.vanhack.ca',
            8086,
            'lasercutter',
            os.getenv('INFLUXDB_PASSWORD'),
            'lasercutter',
        )

    
    def get_avg_energy(self, start, end):
        
        # This InfluxQL query gets the average time that the laser was actually firing, 
        # adjusted by its pwm duty cycle (power level) at each sample.
        q = '''
            SELECT mean(*) FROM (
                SELECT "psu_ttl" * "psu_pwm"
                FROM "autogen"."vhs-laser-mon"
            )
            WHERE time >= '{}'
              AND time <= '{}'
        '''.format(start, end)
        try:
            result = next(self.client.query(q).get_points())
            mean = result['mean_psu_ttl_psu_pwm']

        except StopIteration:
            print("No data: {} {}".format(start, end))
            mean = 0.0

        # Since we consider 60% on our laser to be full-scale, adjust for that
        adjusted_mean = mean / 0.6

        return adjusted_mean



class LaserAnalyze(object):
    """LaserAnalyze is a state machine to step through log message
       and reconstruct laser usage events"""

    def __init__(self):
        self.total_sessions = 0

        self.last_userid = None
        self.start_time = None

        self.cumm_time_per_userid = defaultdict(timedelta)
        self.cumm_energy_per_userid = defaultdict(timedelta)
        self.num_sessions = defaultdict(int)
        self.uid_map = {}

        self.influx = LaserInflux()


    def ingest_logdir(self, dir):
        logfiles = sorted([dir + '/' + fname for fname in os.listdir(dir)])
        for filepath in logfiles:
            with open(filepath, 'r') as fh:
                for line in fh:
                    self.handle_line(line)

        print("Found {} sessions for {} users in {} files".format(
            self.total_sessions, 
            len(self.num_sessions),
            len(logfiles),
        ))

    def handle_line(self, line):
        if 'laser:mmp' in line:
            self.last_userid, name = handle_mmp(line)
            self.uid_map[self.last_userid] = name

        if 'laser:control' in line:
            evt = parse_line(line)
            if evt[2] == 'Laser started':
                self.start_time = evt[0]

            elif evt[2] == 'Laser shutdown':
                if (self.last_userid and self.start_time):
                    self.found_session(self.last_userid, self.start_time, evt[0])
                    self.last_userid = None
                    self.start_time = None

    def found_session(self, user_id, start_time, end_time):
        avg_energy = self.influx.get_avg_energy(start_time, end_time)
        print(user_id, start_time.isoformat(), end_time-start_time, avg_energy)

        self.total_sessions += 1
        self.cumm_time_per_userid[user_id] += end_time-start_time
        self.cumm_energy_per_userid[user_id] += (end_time-start_time) * avg_energy
        self.num_sessions[user_id]+=1

    def print_summary(self):
        # Restructure as a list of tuples of the form (duration, userid)
        users = [(x[1], x[0]) for x in self.cumm_time_per_userid.items()]

        # Sort largest-to-smallest
        for (dur, user_id) in sorted(users, reverse=True):
            print("{} ({} energy) over {} sessions by user {} {}".format(
                dur,
                self.cumm_energy_per_userid[user_id],
                self.num_sessions[user_id],
                user_id,
                self.uid_map[user_id],
            ))


laz = LaserAnalyze()
laz.ingest_logdir('logs')
laz.print_summary()

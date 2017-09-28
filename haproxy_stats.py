#!/usr/bin/python
# This script fetches HAProxy's stats page

import os.path
import time
import platform
import sys
import syslog
import urllib2
import csv
import re
import smtplib
from email.mime.text import MIMEText

HAPROXY_USER    = "haproxyuser"
HAPROXY_PASS    = "haproxypass"
NOTIFY_EMAIL    = "something@example.com"

PIDFILE                 = "/var/run/haproxy/haproxystats.pid"
HOSTNAME                = platform.node()
INTERVAL                = 60
TIMEOUT                 = int(INTERVAL / 10)
METRIC_DELIM    = '.' # for the frontend/backend stats
METRIC_TYPES = {
    'qcur': ('queued_request_count', 'gauge'),
    'max': ('peak_queued_request_count', 'gauge'),
    'scur': ('current_session_count', 'gauge'),
    'smax': ('peak_session_count', 'gauge'),
    'slim': ('max_sessions', 'gauge'),
    'stot': ('session_count', 'counter'),
    'bin': ('bytes_in', 'gauge'),
    'bout': ('bytes_out', 'gauge'),
    'dreq': ('denied_request_count', 'counter'),
    'dresp': ('denied_response_count', 'counter'),
    'ereq': ('error_request_count', 'counter'),
    'econ': ('error_connection_count', 'counter'),
    'eresp': ('error_response_count', 'counter'),
    'wretr': ('conn_retry_count', 'counter'),
    'wredis': ('redispatch_count', 'counter'),
    'weight': ('server_weight', 'gauge'),
    'act': ('active_server_count', 'gauge'),
    'bck': ('backup_server_count', 'gauge'),
    'chkfail': ('failed_check_count', 'counter'),
    'chkdown': ('down_transition_count', 'counter'),
    'lastchg': ('last_change_seconds', 'counter'),
    'downtime': ('downtime_seconds', 'counter'),
    'qlimit': ('max_queue', 'gauge'),
    'throttle': ('throttle_pct', 'gauge'),
    'lbtot': ('selection_count', 'counter'),
    'rate': ('session_rate', 'gauge'),
    'rate_lim': ('max_session_rate', 'gauge'),
    'rate_max': ('peak_session_rate', 'gauge'),
    'check_duration': ('check_duration', 'derive'),
    'hrsp_1xx': ('http_response_1xx', 'counter'),
    'hrsp_2xx': ('http_response_2xx', 'counter'),
    'hrsp_3xx': ('http_response_3xx', 'counter'),
    'hrsp_4xx': ('http_response_4xx', 'counter'),
    'hrsp_5xx': ('http_response_5xx', 'counter'),
    'hrsp_other': ('http_response_other', 'counter'),
    'req_rate': ('request_rate', 'gauge'),
    'req_rate_max': ('peak_request_rate', 'gauge'),
    'req_tot': ('request_count', 'counter'),
    'cli_abrt': ('client_abort_count', 'counter'),
    'srv_abrt': ('server_abort_count', 'counter'),
    'qtime': ('avg_queue_time', 'gauge'),
    'ctime': ('avg_connect_time', 'gauge'),
    'rtime': ('avg_response_time', 'gauge'),
    'ttime': ('avg_total_session_time', 'gauge')
}
VALID_TYPES = [ 'counter', 'derive', 'gauge' ]

class HAProxyStats(object):
        def __init__(self, username, password, uri, port):
                self.hostname = platform.node()
                self.username = username
                self.password = password
                self.uri = uri
                self.port = port
                self.url = "http://127.0.0.1:%s/%s" % (self.port, self.uri)

        def fetch_stats (self):
                try:
                        passman = urllib2.HTTPPasswordMgrWithDefaultRealm()
                        passman.add_password(None, self.url, self.username, self.password)
                        urllib2.install_opener(urllib2.build_opener(urllib2.HTTPBasicAuthHandler(passman)))
                        req = urllib2.Request(self.url)
                        f = urllib2.urlopen(req, None, TIMEOUT)
                except:
                        body = "Failed to connect to %s. Which indicates a problem with binding of haproxy on %s. Make sure that haproxy is running as expected and listening on ports 7710-7720. Also check the monit log for excessive restarting.\n\nThis was the python exception: %s" % (self.url, HOSTNAME, sys.exc_info()[0])
                        subject = 'Failed to collect haproxy stats on %s' % HOSTNAME
                        self.notify_email (NOTIFY_EMAIL, subject, body)
                        syslog.syslog(syslog.LOG_ERR, "Failed to open the stats url: %s" % self.url)
                else:
                        output = f.read()
                        output = output.lstrip('# ').strip()
                        output = [ l.strip(',') for l in output.splitlines() ]
                        csvreader = csv.DictReader(output)
                        result = [ d.copy() for d in csvreader ]
                        return result

        def get_stats (self):
                server_stats = self.fetch_stats()
                stats = {}
                for statdict in server_stats:
                        # only do aggregate stats, not server specific
                        if statdict['svname'] not in ('FRONTEND','BACKEND'):
                                continue
                        for key,val in statdict.items():
                                if key in METRIC_TYPES:
                                        if "monitoring" in statdict['pxname'].lower():
                                                continue
                                        metricname = METRIC_DELIM.join([ statdict['svname'].lower(), statdict['pxname'].lower(), key ])
                                        try:
                                                stats[metricname] = [int(val), METRIC_TYPES[key][1]]
                                        except (TypeError, ValueError), e:
                                                pass
                return stats

        def putval (self, collectdtype, k, v):
                now = int(time.time())
                if collectdtype in VALID_TYPES:
                        return "PUTVAL \"%s/exec-haproxy/%s-%s\" INTERVAL=%s %s:%s" % (self.hostname, collectdtype, k, INTERVAL, now, v)

        def print_collectd (self, inDict):
                for k,v in inDict.items():
                        print self.putval(v[1], k, v[0])

        def notify_email (self, to, subject, body):
                msg = MIMEText(body)
                msg['Subject'] = subject
                msg['To'] = to
                msg['From'] = "haproxy@%s" % HOSTNAME

                s = smtplib.SMTP('localhost')
                s.sendmail(msg['From'], to, msg.as_string())
                s.quit()

def find_nbproc():
        try:
                f = open('/etc/haproxy/haproxy.cfg')
        except IOError as e:
                print "I/O error({0}): {1}".format(e.errno, e.strerror)
                return False

        try:
                content = f.readlines()
        except:
                print "Unexpected error:", sys.exc_info()[0]
        finally:
                f.close()

        for c in content:
                c = c.strip(' \t\n\r')
                match = re.search('nbproc\s*([\d]+)', c)
                if match:
                        return int(match.group(1))

def get_ports():
        ports = []
        try:
                nbproc = find_nbproc()
        except:
                print "Unexpected error:", sys.exc_info()[0]
                nbproc = 0
                pass

        if nbproc > 0:
                for num in range(0, nbproc):
                        ports.append(7710 + num)
        else:
                ports = [80]
        return ports

if __name__ == '__main__':
        pid = str(os.getpid())
        syslog.openlog("%s[%d]" % (os.path.basename(sys.argv[0]), os.getpid()), 0, syslog.LOG_DAEMON)

        if os.path.isfile(PIDFILE):
                checkpid = file(PIDFILE, 'r').read()
                if os.path.exists("/proc/%s" % checkpid):
                        syslog.syslog(syslog.LOG_ERR, "%s already exists, exiting" % PIDFILE)
                        sys.exit()
                else:
                        syslog.syslog(syslog.LOG_ERR, "Stale PIDFILE removed")
                        os.unlink(PIDFILE)

        file(PIDFILE, 'w').write(pid)

        ports = get_ports()
        all = []
        res = {}

        for port in ports:
                ha = HAProxyStats(HAPROXY_USER, HAPROXY_PASS, "admin?status;csv;norefresh", port)
                stats = ha.get_stats()
                all.append(stats)

        for a in all:
                for k,v in a.items():
                        if k not in res:
                                res[k] = v
                        else:
                                res[k][0] += v[0]

        ha.print_collectd(res)

        os.unlink(PIDFILE)

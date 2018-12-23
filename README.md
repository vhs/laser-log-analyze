# laser-log-analyze

### Dependencies

`pip install influxdb`

### Usage

 * With LCC's permission, pull the latest log files off the laser pi
 * Create a subdirectory called `logs` and place the log files within
 * `INFLUXDB_PASSWORD=<influxlaserpassword> python analyze.py`


##Tool to enable SSL for the services in HDP stack

Steps to run the SSL Manager: 

- Set java `export JAVA_HOME=<path to java>`
- Update ca.properties with CA properties, Keystore & truststore passwords and the hostnames of cluster.
- To enable ssl for all services and ui's :
`./bin/ssl_manager.py --ca --properties=conf/ca.properties --scpKeyFile=<pem> --enable-ssl --service=all --ui=all  --host <ambari-host> --cluster <clustername>`
- To disable ssl for all services and ui's :
`./bin/ssl_manager.py --disable-ssl --host <ambari-host> --cluster <clustername> --service all --ui all`



``` Usage: ssl_manager.py [options] arg1

Options:
  -h, --help            show this help message and exit
  -v, --verbose
  --ca                  Create a CA using tls toolkit.
  --properties=PROPERTIES
                        ca.properties file which is used to create a CA.
  --scpKeyFile=SCPKEYFILE
                        sshkey to copy the certificates to all the hosts.
  --scpUserName=SCPUSERNAME
                        username to copy the certificates to all the hosts.
  --enable-ssl          Enables ssl for HDP stack.
  --disable-ssl         Disables ssl for HDP stack.
  --service=SERVICE     Comma separated list of services for which SSL needs
                        to be enabled.'all' or comma seperated services.
                        Available configs are:['HDFS', 'YARN', 'MRSHUFFLE',
                        'TEZ', 'HIVE', 'KAFKA', 'RANGER', 'SPARK', 'SPARK2',
                        'RANGERADMIN', 'RANGERPLUGINS']
  --ui=UI               Comma separated list of UI's for which SSL needs to be
                        enabled. 'all' or comma seperated uis. Available ui's
                        are:['HDFSUI', 'YARN', 'MAPREDUCE2UI', 'HBASE', 'OOZIE',
                        'AMBARI_INFRA', 'ATLAS', 'ZEPPELIN', 'STORM',
                        'AMBARIUI'].
  --user=USER           Optional user ID to use for ambari authentication.
                        Default is 'admin'
  --password=PASSWORD   Optional password to use for ambari authentication.
                        Default is 'admin'
  --port=PORT           Optional port number for Ambari server. Default is
                        '8080'.Provide empty string to not use port.
  --protocol=PROTOCOL   Ambari server protocol. Default protocol is 'http'
  --host=HOST           Ambari Server external host name
  --cluster=CLUSTER     Name given to cluster. Ex: 'c1'
```

##How to Build

- Make sure you are in ssl_manager directory : `cd ssl_manager`
- Build using : 
`mvn clean install -DskipTests`
- ssl_manager-\<version>-all.tar will be generated under target directory: 
`target/ssl_manager-1.5.0-all.tar`
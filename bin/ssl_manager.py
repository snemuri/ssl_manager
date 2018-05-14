#!/usr/bin/env python

import os
import sys
import logging
import json
import yaml
import base64
import subprocess
from optparse import OptionParser
import configs  # configs.py from ambari


logger = logging.getLogger(__name__)

CA_DIR = os.getcwd()
CA_CONF_DIR = "conf"

#####
ALL_SERVICES = ['HDFS', 'YARN', 'MAPREDUCE2', 'TEZ', 'HIVE', 'KAFKA', 'RANGER', 'SPARK', 'SPARK2']
RANGER = ['RANGERADMIN', 'RANGERPLUGINS']

ALL_UI = ['HDFS', 'YARN', 'MAPREDUCE2', 'HBASE', 'OOZIE', 'AMBARI_INFRA', 'ATLAS', 'ZEPPELIN', 'STORM']
AMBARI = ['AMBARIUI']
#####

# Properties to enable ssl
SERVICES_CONFIGS = os.path.join(CA_CONF_DIR, 'configs.yaml')

# Properties to disable ssl
DISABLE_CONFIGS = os.path.join(CA_CONF_DIR, 'disable_configs.yaml')

# Location of certificates across all nodes.
CERT_DIR = "/etc/security/certificates"


KEYSTORE = 'keystore.jks'
TRUSTSTORE = 'truststore.jks'
AMBARI_P12 = 'ambari-keystore.p12'
AMBARI_PEM = 'ambari-keystore.pem'
AMBARI_CRT = 'ambari-keystore.crt'
KEYSTORE_LOCATION = os.path.join(CERT_DIR, 'keystore.jks')
TRUSTSTORE_LOCATION = os.path.join(CERT_DIR, 'truststore.jks')
keystorepassword = ""
truststorepassword = ""
accessor = ""
IS_HADOOP = ['HDFS', 'YARN', 'MAPREDUCE2', 'TEZ', 'HBASE']

CA = \
    """
    Generated a CA and server certificates for all the hosts:

    - Copy keystore.jks and truststore.jks files from host directories to respective hosts at /etc/security/certificates
    - Change the permissions "chmod 755 -R /etc/security/certificates"
    """

# #### wget -O /usr/hdp/2.6.4.0-91/oozie/libext/ext-2.2.zip http://tiny.cloudera.com/oozie-ext-2.2
OOZIE_UI = \
    """
    Select Oozie > Configs, then select Advanced oozie-env and set the following properties:

export OOZIE_HTTPS_PORT=11443
export OOZIE_HTTPS_KEYSTORE_FILE=/etc/security/certificates/keystore.jks
export OOZIE_HTTPS_KEYSTORE_PASS=hadoop
export OOZIE_CLIENT_OPTS="${OOZIE_CLIENT_OPTS} -Doozie.connection.retry.count=5 -Djavax.net.ssl.trustStore=/etc/security/certificates/truststore.jks -Djavax.net.ssl.trustStorePassword=hadoop"

    Login to Oozie server and run: su -l oozie -c "/usr/hdp/current/oozie-server/bin/oozie-setup.sh prepare-war -secure"

    Note: Make sure Ext JS library is Installed and UI is already enabled.
    """

ATLAS_UI = \
    """

    Login to Atlas metadata server and create a .jceks file as shown below:
    ----
    cd /usr/hdp/current/atlas-server/bin
    ./cputil.py
    Please enter the full path to the credential provider:jceks://file//etc/security/certificates/ssl.jceks
    Please enter the password value for keystore.password:<keypass>
    Please enter the password value for keystore.password again:<keypass>
    Please enter the password value for truststore.password:<keypass>
    Please enter the password value for truststore.password again:<keypass>
    Please enter the password value for password:<keypass>
    Please enter the password value for password again:<keypass>
    ----

    """


def generate_ca(properties, host):
    """
    Generated a CA and server certificates for all the provided hosts using Tls toolkit.\
    Please copy the keystore.jks and truststore.jks files under host directory to respective hosts at /etc/security/certificates/
    Change the permissions to '755' using "chmod 755 /etc/security/certificates/*"
    """
    try:
        os.path.exists(CA_DIR)
    except OSError:
        raise
    logger.info("Using {0} as base path.".format(CA_DIR))
    if os.path.exists(properties):
        ca_props = read_ca_conf_file(properties)
        logger.debug("CA properties are:".format(ca_props))
        get_opdir = ca_props.index('--outputDirectory')
        opdir = os.path.abspath(ca_props[get_opdir+1])
        toolkit_cmd = ['java', '-jar', '-Xms12m', '-Xmx24m', CA_DIR + '/lib/ssl_manager-1.5.0-jar-with-dependencies.jar'
                       , 'standalone', '--certificateAuthorityHostname', host]
        create_ca = toolkit_cmd + ca_props
        logger.debug("tls toolkit args are : {0}".format(create_ca))
        cacmd = subprocess.Popen(create_ca)
        cacmd.communicate()
        returncode = cacmd.poll()
        if not returncode == 0:
            logger.error("Unable to execute: {0}".format(create_ca))
            sys.exit(1)
        generate_ambari_specific(host, opdir)
    return


def generate_ambari_specific(host, outputDirectory):
    ambari_host = host
    ambari_keystore = os.path.join(outputDirectory, ambari_host, 'keystore.jks')
    ambari_p12 = os.path.join(outputDirectory, ambari_host, 'ambari-keystore.p12')
    ambari_pem = os.path.join(outputDirectory, ambari_host, 'ambari-keystore.pem')
    ambari_crt = os.path.join(outputDirectory, ambari_host, 'ambari-keystore.crt')

    logger.info("Keystore is:{0}".format(ambari_keystore))
    logger.info("P12 is:{0}".format(ambari_p12))

    createp12 = ['keytool', '-importkeystore', '-srckeystore', ambari_keystore,
                 '-destkeystore', ambari_p12, '-srcstoretype', 'jks',
                 '-deststoretype', 'pkcs12', '-srcstorepass', keystorepassword, '-deststorepass', keystorepassword]
    createpem = ['openssl', 'pkcs12', '-in', ambari_p12, '-out', ambari_pem, '-passin',
                 'pass:'+keystorepassword, '-passout', 'pass:'+keystorepassword]
    createcrt = ['openssl', 'x509', '-in', ambari_pem, '-out', ambari_crt]

    logger.info("Creating ambari-keystore.p12 for ambari...")
    subprocess.Popen(createp12).communicate()
    logger.info("Creating ambari-keystore.pem for ambari...")
    subprocess.Popen(createpem).communicate()
    logger.info("Creating ambari-keystore.crt for ambari...")
    subprocess.Popen(createcrt).communicate()
    return


def read_service_configs(service_name, config_file):
    ssl_configs = ""
    try:
        os.path.exists(config_file)
        with open(config_file) as f:
            config = yaml.safe_load(f)
    except OSError as e:
        logger.error(e)
        return 1
    if service_name in config.keys():
        logger.info("Reading SSL configs for service:{0}".format(service_name))
        ssl_configs = config[service_name]
    else:
        logger.warn("Unable to find SSL configs for: {0} in {1}".format(service_name, SERVICES_CONFIGS))
        logger.warn("Available configs are: {0}".format(config.keys()))
    #    Consider only installed ranger plugins
    if service_name == "RANGERPLUGINS":
        plugins_to_be_considered = []
        for i in services_to_be_considered:
            plugins_to_be_considered.append('ranger-'+i.lower()+'-policymgr-ssl')
        for i in ui_to_be_considered:
            plugins_to_be_considered.append('ranger-'+i.lower()+'-policymgr-ssl')
        ssl_configs = filter(lambda plugins: plugins['config_type'] in plugins_to_be_considered, ssl_configs)
    return ssl_configs


def get_configs(accessor, cluster, config_type):
    try:
        properties, attributes = configs.get_current_config(cluster, config_type, accessor)
    except KeyError:
        # This is to fix empty ranger-site
        properties, attributes = {}, {}
    config = properties, attributes
    logger.debug("Got configs from Ambari for {0}: {1}".format(config_type, json.dumps(config, indent=2)))
    return config


def put_configs(config):
    def update(cluster, config_type, accessor):
        if config[0] is None:
            config[0] = {}
        if config[1] is None:
            config[1] = {}
        new_properties = config[0]
        new_attributes = config[1]
        logger.debug('### PUTting : "{0}"'.format(json.dumps(config, indent=2)))
        return new_properties, new_attributes
    return update


def get_password(properties, pwd_type):
    password = ""
    conf = read_conf_file(properties)
    if pwd_type is "keyStorePassword":
        password = base64.b64decode(conf['keyStorePassword'])
    elif pwd_type is "trustStorePassword":
        password = base64.b64decode(conf['trustStorePassword'])
    return password


def update_configs_ambari(services, accessor, cluster):
    config = {}
    for s_name in services.split(','):
        logger.debug("Reading SSL configs from {0}".format(SERVICES_CONFIGS))
        ssl_configs = read_service_configs(s_name.upper(), SERVICES_CONFIGS)
        logger.debug("ssl_configs for {0} are {1}".format(s_name.upper(), ssl_configs))
        for section in ssl_configs:
            config_type = section['config_type']
            del section['config_type']
            try:
                config = get_configs(accessor, cluster, config_type)
            except Exception:
                logger.warn("Unable to get configs for config_type:{0} from Ambari".format(config_type))
                return 1
            for k in section:
                if section[k] == "$keystore":
                    section[k] = KEYSTORE_LOCATION
                elif section[k] == "$truststore":
                    section[k] = TRUSTSTORE_LOCATION
                elif section[k] == "$keystorepassword":
                    section[k] = keystorepassword
                elif section[k] == "$truststorepassword":
                    section[k] = truststorepassword
                elif section[k] == "$resourcemanager":
                    section[k] == config[0].get("yarn.resourcemanager.webapp.https.address").replace('8088', '8190')
                elif section[k] == "$historyserver":
                    section[k] = config[0].get("yarn.log.server.url").replace('http', 'https').replace('19888', '19890')
                elif section[k] == "$timelineserver":
                    section[k] = config[0].get("yarn.log.server.web-service.url").replace('http', 'https').replace('8188', '8190')
                config[0].update({k: section[k]})
            updater = put_configs(config)
            configs.update_config(cluster, config_type, updater, accessor)
            logger.info("Updated configurations for service {0}[{1}]".format(s_name, config_type))
    return


def disable_configs(service, accessor, cluster):
    logger.debug("Reading SSL configs from {0}".format(DISABLE_CONFIGS))
    ssl_configs = read_service_configs(service, DISABLE_CONFIGS)
    logger.debug("ssl_configs for {0} are {1}".format(service, ssl_configs))

    for section in ssl_configs:
        config_type = section['config_type']
        keys = section.keys()
        del section['config_type']
        if "delete" in keys:
            del section['delete']
            for k in section:
                configs.update_config(cluster, config_type, configs.delete_specific_property(k), accessor)
                logger.info("Disabled SSL for service {0}[{1}]".format(service, config_type))
        else:
            config = get_configs(accessor, cluster, config_type)
            for k in section:
                if section[k] == "$historyserver":
                    section[k] = config[0].get("yarn.log.server.url").replace('https', 'http').replace('19890', '19888')
                elif section[k] == "$timelineserver":
                    section[k] = config[0].get("yarn.log.server.web-service.url").replace('https', 'http').replace('8190', '8188')
                config[0].update({k: section[k]})
            logger.debug("New configs for {0} are :{1}".format(config_type, json.dumps(config, indent=2)))
            updater = put_configs(config)
            configs.update_config(cluster, config_type, updater, accessor)
            logger.info("Disabled SSL for service {0}[{1}]".format(service, config_type))
    return


def copy_certs(properties, ssh_key, scpusername):
    conf = read_conf_file(properties)
    opdir = os.path.abspath(conf['outputDirectory'])
    host_list = conf['hostnames']
    ssh_key = os.path.expanduser(ssh_key)
    for host in host_list.split(','):
        logger.info(host)
        source = os.path.join(opdir, host)+'/*'
        dest = scpusername + '@' + host + ':' + CERT_DIR + '/'
        userhost = scpusername + '@' + host
        scp_command = "scp -o StrictHostKeyChecking=no -i " + ssh_key + " " + source + " "+dest
        logger.info("Creating cert dir {0} in host {1}".format(CERT_DIR, host))
        subprocess.Popen(['ssh', '-o', 'StrictHostKeyChecking=no', '-i', ssh_key, userhost, 'mkdir', '-p',
                          CERT_DIR]).communicate()
        logger.info("Copying certs to host {0}".format(host))
        subprocess.Popen(scp_command, shell=True).communicate()
        logger.info("Changing the permissions..")
        subprocess.Popen(['ssh', '-o', 'StrictHostKeyChecking=no', '-i', ssh_key, userhost, 'chmod', '-R', '755',
                          CERT_DIR]).communicate()
    return


def read_ca_conf_file(file_path):
    """
    Parse the configuration file, and return a dictionary of key, value pairs.
    Ignore any lines that begin with #
    :param file_path: Properties file to parse.
    :return: List with key, value pairs.
    """
    ca_props = []
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            lines = f.readlines()
        if lines:
            logger.debug("Reading file {0}, has {1} lines.".format(file_path, len(lines)))
            for l in lines:
                l = l.replace(" ", "").strip()
                if l.startswith("#"):
                    continue
                parts = l.split("=")
                if len(parts) >= 2:
                    if parts[0] == "keyStorePassword":
                        parts[1] = keystorepassword
                    elif parts[0] == "trustStorePassword":
                        parts[1] = truststorepassword
                    ca_props.append("--"+parts[0])
                    ca_props.append(parts[1])
    return ca_props


def read_conf_file(file_path):
    """
    Parse the configuration file, and return a dictionary of key, value pairs.
    Ignore any lines that begin with #
    :param file_path: Properties file to parse.
    :return: Dictionary with key, value pairs.
    """
    ca_props = {}
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            lines = f.readlines()
            if lines:
                logger.debug("Reading file {0}, has {1} lines.".format(file_path, len(lines)))
                for l in lines:
                    l = l.replace(" ","").strip()
                    if l.startswith("#"):
                        continue
                    parts = l.split("=")
                    if len(parts) >= 2:
                        prop = parts[0]
                        value = "".join(parts[1:])
                        ca_props[prop] = value
    return ca_props


def delete_properties(cluster, config_type, args, accessor):
    logger.info('### Performing "delete":')
    if len(args) == 0:
        logger.error("Not enough arguments. Expected config key.")
        return -1

    config_name = args[0]
    logger.info('### on property "{0}"'.format(config_name))
    configs.update_config(cluster, config_type, configs.delete_specific_property(config_name), accessor)
    return 0


def disable_service(services, cluster):
    for servicename in services:
        s_name = servicename.upper()
        logger.info(s_name)
        if s_name == 'ALL':
            for i in services_to_be_considered:
                logger.info("Disabling ssl for {0}".format(i))
                disable_configs(i.upper(), accessor, cluster)
        else:
            disable_configs(s_name, accessor, cluster)
    return


def disable_ui(uis, cluster):
    for uiname in uis:
        u_name = uiname.upper()
        logger.info(u_name)
        if u_name == 'ALL':
            for i in ui_to_be_considered:
                if i == "AMBARIUI":
                    logger.info("Disabling ssl for {0}".format(i))
                    subprocess.Popen(disable_ambari_ui()).communicate()
                else:
                    logger.info("Disabling ssl for {0}".format(i))
                    disable_configs(i.upper(), accessor, cluster)
        else:
            if u_name == "AMBARIUI":
                subprocess.Popen(disable_ambari_ui()).communicate()
            else:
                disable_configs(u_name, accessor, cluster)
    return


def parse_service(services, accessor, cluster):
    for servicename in services:
        s_name = servicename.upper()
        logger.info(s_name)
        if s_name == 'ALL':
            for i in services_to_be_considered:
                logger.info("Enabling ssl for {0}".format(i))
                update_configs_ambari(i.upper(), accessor, cluster)
        else:
            update_configs_ambari(s_name, accessor, cluster)
    return


def parse_ui(uis, accessor, cluster):
    for uiname in uis:
        u_name = uiname.upper()
        logger.info(u_name)
        if u_name == 'ALL':
            for i in ui_to_be_considered:
                logger.info("Enabling ssl for {0}".format(i))
                if i.upper() == "AMBARIUI":
                    subprocess.Popen(enable_ambari_ui()).communicate()
                elif i.upper() == 'OOZIE':
                    logger.info("Configs to update in {0} are: {1}".format(i.upper(), OOZIE_UI))
                elif i.upper() == 'ATLAS':
                    update_configs_ambari(i.upper(), accessor, cluster)
                    logger.info("Perform below operation to enable ssl for {0}: {1}".format(i.upper(), ATLAS_UI))
                else:
                    update_configs_ambari(i.upper(), accessor, cluster)

        else:
            if u_name == 'AMBARIUI':
                subprocess.Popen(enable_ambari_ui()).communicate()
                logger.info("Enabling ssl for {0} using : {1}".format(u_name, enable_ambari_ui()))
            elif u_name == 'OOZIE':
                logger.info("Configs to update in {0} are: {1}".format(u_name, OOZIE_UI))
            elif u_name == 'ATLAS':
                update_configs_ambari(u_name, accessor, cluster)
                logger.info("Perform below operation to enable ssl for {0}: {1}".format(u_name, ATLAS_UI))
            else:
                logger.info("Enabling ssl for {0}".format(u_name))
                update_configs_ambari(u_name, accessor, cluster)
    return


def is_hadoop_required(a, b):
    return any([i in b for i in a])


def enable_ambari_ui():
    ambari_ui = ['ambari-server', 'setup-security', '--security-option=setup-https', '--api-ssl=true',
                 '--api-ssl-port=8443', '--import-cert-path='+os.path.join(CERT_DIR, AMBARI_CRT),
                 '--import-key-path='+os.path.join(CERT_DIR, AMBARI_PEM), '--pem-password='+keystorepassword]
    return ambari_ui


def disable_ambari_ui():
    ambari_ui = ['ambari-server', 'setup-security', '--security-option=setup-https', '--api-ssl=false']
    return ambari_ui


def main():
    parser = OptionParser(usage="usage: %prog [options] arg1", )
    parser.add_option("-v", "--verbose", action="store_true", dest="verbose", default="False")
    parser.add_option("--ca", action="store_true", default=False, dest="ca",
                      help="Create a CA using tls toolkit.")
    parser.add_option("--properties", dest="properties",
                      help="ca.properties file which is used to create a CA.")
    parser.add_option("--scpKeyFile", dest="scpKeyFile",
                      help="sshkey to copy the certificates to all the hosts.")
    parser.add_option("--scpUserName", dest="scpUserName",
                      help="username to copy the certificates to all the hosts.")
    parser.add_option("--enable-ssl", action="store_true", default=False,
                      dest="enablessl", help="Enables ssl for HDP stack.")
    parser.add_option("--disable-ssl", action="store_true", default=False,
                      dest="disablessl", help="Disables ssl for HDP stack.")
    parser.add_option("--service", help="Comma separated list of services for which SSL "
                                        "needs to be enabled.'all' or comma seperated services. "
                                        "Available configs are: HDFS,YARN,MRSHUFFLE,TEZ,HIVE,KAFKA,SPARK,SPARK2,RANGERADMIN,RANGERPLUGINS")
    parser.add_option("--ui", dest="ui", help="Comma separated list of UI's for which SSL needs "
                                              "to be enabled. 'all' or comma seperated uis. "
                                              "Available ui's are: HDFSUI,YARN,MAPREDUCE2UI,HBASE,OOZIE,AMBARI_INFRA,ATLAS,ZEPPELIN,STORM,AMBARIUI.")

    # Ambari arguments

    parser.add_option("--user", dest="user", default="admin",
                      help="Optional user ID to use for ambari authentication. Default is 'admin'")
    parser.add_option("--password", dest="password", default="admin",
                      help="Optional password to use for ambari authentication. Default is 'admin'")
    parser.add_option("--port", dest="port", default="8080",
                      help="Optional port number for Ambari server. Default is '8080'."
                           "Provide empty string to not use port.")
    parser.add_option("--protocol", dest="protocol", default="http",
                      help="Ambari server protocol. Default protocol is 'http'")
    parser.add_option("--host", dest="host", help="Ambari Server external host name")
    parser.add_option("--cluster", dest="cluster", help="Name given to cluster. Ex: 'c1'")

    (options, args) = parser.parse_args()
    if options.enablessl is False and options.disablessl is False:
        parser.error("wrong number of arguments,Option --enable-ssl or --disable-ssl is mandatory.")
    # if not (options.service or options.ui) or (options.ca is False):
    #     parser.error("wrong number of arguments")
    if not (options.service or options.ui):
        parser.error("Choose service or ui for which you wish to enable SSL.")
    if options.ca is True and not options.properties:
        parser.error("Along with --ca, you should pass ca.properties using --properties")
    if options.enablessl is True and not options.properties:
        parser.error("Along with --enable-ssl, you should pass ca.properties using --properties")
    if None in [options.host, options.cluster]:
        parser.error("Ambari host / Cluster name are not passed")
    if options.scpKeyFile is not None and not os.path.exists(os.path.expanduser(options.scpKeyFile)):
        parser.error("{0} doesn't exists.".format(os.path.expanduser(options.scpKeyFile)))

    if options.verbose is True:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO
    logger.setLevel(loglevel)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(loglevel)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    logger.debug("In verbose mode...\nCli args are:{0}".format(options))

    ca = options.ca
    properties = options.properties
    scpkeyfile = options.scpKeyFile
    scpusername = options.scpUserName
    service = options.service
    ui = options.ui
    user = options.user
    password = options.password
    port = options.port
    protocol = options.protocol
    host = options.host
    cluster = options.cluster
    enable = options.enablessl
    disable = options.disablessl

    # Init global variables
    global accessor
    accessor = configs.api_accessor(host, user, password, protocol, port)

    global services_to_be_considered
    global ui_to_be_considered

    # Get installed services from ambari and take the intersection with the available ones.
    installed_services = configs.get_installed_services(cluster, accessor)

    services_to_be_considered = list(set(ALL_SERVICES).intersection(installed_services))
    if "RANGER" in services_to_be_considered:
        services_to_be_considered.remove("RANGER")
        services_to_be_considered = services_to_be_considered + RANGER
    if is_hadoop_required(services_to_be_considered, IS_HADOOP) is True:
        services_to_be_considered.append('HADOOP')
    if "MAPREDUCE2" in services_to_be_considered:
        services_to_be_considered.remove("MAPREDUCE2")
        services_to_be_considered.append("MRSHUFFLE")

    ui_to_be_considered = list(set(ALL_UI).intersection(installed_services))
    ui_to_be_considered = ui_to_be_considered + AMBARI
    if is_hadoop_required(ui_to_be_considered, IS_HADOOP) is True:
        ui_to_be_considered.append('HADOOP')
    if "HDFS" in ui_to_be_considered:
        ui_to_be_considered.remove("HDFS")
        ui_to_be_considered.append('HDFSUI')
    if "MAPREDUCE2" in ui_to_be_considered:
        ui_to_be_considered.remove("MAPREDUCE2")
        ui_to_be_considered.append('MAPREDUCE2UI')

    if disable is True:
        if service is not None:
            services = service.split(',')
            if is_hadoop_required(services, IS_HADOOP) is True:
                services.append('HADOOP')
            logger.info("my services are {0}".format(services))
            disable_service(services, cluster)
        if ui is not None:
            uis = ui.split(',')
            if is_hadoop_required(uis, IS_HADOOP) is True:
                uis.append('HADOOP')
            disable_ui(uis, cluster)

    elif enable is True:
        global keystorepassword
        keystorepassword = get_password(properties, "keyStorePassword")
        global truststorepassword
        truststorepassword = get_password(properties, "trustStorePassword")

        if ca is True:
            generate_ca(properties, host)
            if scpkeyfile is not None:
                if scpusername is not None:
                    copy_certs(properties, scpkeyfile, scpusername)
                else:
                    copy_certs(properties, scpkeyfile, os.environ.get('USER'))
            else:
                logger.info(CA)

        if service is not None:
            services = service.split(',')
            if is_hadoop_required(services, IS_HADOOP) is True:
                services.append('HADOOP')
            for i in services:
                if i == 'MAPREDUCE2':
                    services[services.index('MAPREDUCE2')] = 'MRSHUFFLE'
            logger.info("Services's to enable SSL are {0}".format(services_to_be_considered))
            parse_service(services, accessor, cluster)

        if ui is not None:
            uis = ui.split(',')
            if is_hadoop_required(uis, IS_HADOOP) is True:
                uis.append('HADOOP')
            for i in uis:
                if i == 'HDFS':
                    uis[uis.index('HDFS')] = 'HDFSUI'
                if i == 'MAPREDUCE2':
                    uis[uis.index('MAPREDUCE2')] = 'MAPREDUCE2UI'
            logger.info("UI's to enable SSL are {0}".format(ui_to_be_considered))

            parse_ui(uis, accessor, cluster)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nAborting ... Keyboard Interrupt.")
        sys.exit(1)

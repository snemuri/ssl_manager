#!/usr/bin/env python

import os
import io
import sys
import logging
import json
import glob
import base64
import subprocess
import ConfigParser
from optparse import OptionParser
import configs  # configs.py from ambari


logger = logging.getLogger(__name__)

CA_DIR = os.getcwd()
CA_CONF_DIR = "conf"

#####
ALL_SERVICES = ['HDFS', 'MRSHUFFLE', 'TEZ', 'HIVE', 'KAFKA', 'RANGER', 'SPARK', 'SPARK2']
RANGER = ['RANGERADMIN', 'RANGERPLUGINS']

ALL_UI = ['HDFSUI', 'YARN', 'MAPREDUCE2UI', 'HBASE', 'OOZIE', 'AMBARI_INFRA', 'AMBARI_INFRA_SOLR', 'ATLAS', 'ZEPPELIN', 'STORM']
AMBARI = ['AMBARIUI']
#####

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
IS_HADOOP = ['HDFS', 'HDFSUI', 'YARN', 'MRSHUFFLE', 'MAPREDUCE2UI', 'TEZ', 'HBASE']

CA = \
    """
    Generated a CA and server certificates for all the hosts:

    - Copy keystore.jks and truststore.jks files from host directories to respective hosts at /etc/security/certificates
    - Change the permissions "chmod 750 -R /etc/security/certificates"
    - Change the ownership to root:hadoop "chown -R root:hadoop /etc/security/certificates"
    """

# #### wget -O /usr/hdp/2.6.4.0-91/oozie/libext/ext-2.2.zip http://tiny.cloudera.com/oozie-ext-2.2
OOZIE_UI = \
    """
    Select Oozie > Configs, then select Advanced oozie-env and set the following properties (update the <password> below):

export OOZIE_HTTPS_PORT=11443
export OOZIE_HTTPS_KEYSTORE_FILE=/etc/security/certificates/keystore.jks
export OOZIE_HTTPS_KEYSTORE_PASS=<password>
export OOZIE_CLIENT_OPTS="${OOZIE_CLIENT_OPTS} -Doozie.connection.retry.count=5 -Djavax.net.ssl.trustStore=/etc/security/certificates/truststore.jks -Djavax.net.ssl.trustStorePassword=<password>"

    Login to Oozie server and run: su -l oozie -c "/usr/hdp/current/oozie-server/bin/oozie-setup.sh prepare-war -secure"

    Note: Make sure Ext JS library is Installed and UI is already enabled.
    """
DISABLE_OOZIE_UI = \
    """
    Select Oozie > Configs, then select Advanced oozie-env and remove the following properties:

export OOZIE_HTTPS_PORT=11443
export OOZIE_HTTPS_KEYSTORE_FILE=/etc/security/certificates/keystore.jks
export OOZIE_HTTPS_KEYSTORE_PASS=<password>
export OOZIE_CLIENT_OPTS="${OOZIE_CLIENT_OPTS} -Doozie.connection.retry.count=5 -Djavax.net.ssl.trustStore=/etc/security/certificates/truststore.jks -Djavax.net.ssl.trustStorePassword=<password>"

    Login to Oozie server and run: su -l oozie -c "/usr/hdp/current/oozie-server/bin/oozie-setup.sh prepare-war"

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


def generate_ca(properties, host, isoverwrite):
    """
    Generated a CA and server certificates for all the provided hosts using Tls toolkit.\
    Please copy the keystore.jks and truststore.jks files under host directory to respective hosts at /etc/security/certificates/
    Change the permissions to '750' using "chmod 750 /etc/security/certificates/*"
    """
    java_home = read_conf_file(properties, "env", "JAVA_HOME")
    java = java_home+'/bin/java'
    logger.info("Using JAVA {0}...".format(java))

    try:
        os.path.exists(CA_DIR)
    except OSError:
        raise
    logger.info("Using {0} as base path.".format(CA_DIR))
    if os.path.exists(properties):
        ca_props = read_ca_conf_file(properties, "caprops")
        logger.debug("CA properties are:".format(ca_props))
        opdir = os.path.abspath(read_conf_file(properties, "caprops", "outputDirectory"))
        toolkit_cmd = [java, '-jar', '-Xms12m', '-Xmx24m', CA_DIR + '/lib/ssl_manager-1.5.0-jar-with-dependencies.jar'
                       , 'standalone', '--certificateAuthorityHostname', read_conf_file(properties, "caprops", "caName")]
        if isoverwrite is True:
            toolkit_cmd.append("--isOverwrite")
        create_ca = toolkit_cmd + ca_props
        logger.debug("tls toolkit args are : {0}".format(create_ca))
        cacmd = subprocess.Popen(create_ca)
        cacmd.communicate()
        returncode = cacmd.poll()
        if not returncode == 0:
            logger.error("Unable to execute: {0}".format(create_ca))
            sys.exit(1)
        generate_ambari_specific(properties, host, opdir)
    return


def generate_ambari_specific(properties, host, outputdirectory):
    ambari_host = host
    ambari_keystore = os.path.join(outputdirectory, ambari_host, 'keystore.jks')
    ambari_p12 = os.path.join(outputdirectory, ambari_host, 'ambari-keystore.p12')
    ambari_pem = os.path.join(outputdirectory, ambari_host, 'ambari-keystore.pem')
    ambari_crt = os.path.join(outputdirectory, ambari_host, 'ambari-keystore.crt')

    logger.info("Keystore is:{0}".format(ambari_keystore))
    logger.info("P12 is:{0}".format(ambari_p12))

    java_home = read_conf_file(properties, "env", "JAVA_HOME")
    keytool = java_home+'/bin/keytool'
    logger.info("Using Keytool {0}...".format(keytool))

    createp12 = [keytool, '-importkeystore', '-srckeystore', ambari_keystore,
                 '-destkeystore', ambari_p12, '-srcstoretype', 'jks',
                 '-deststoretype', 'pkcs12', '-srcstorepass', keystorepassword, '-deststorepass', keystorepassword]
    createpem = ['openssl', 'pkcs12', '-in', ambari_p12, '-out', ambari_pem, '-passin',
                 'pass:'+keystorepassword, '-passout', 'pass:'+keystorepassword]
    createcrt = ['openssl', 'x509', '-in', ambari_pem, '-out', ambari_crt]

    logger.info("Creating ambari-keystore.p12 for ambari...")
    cmd = subprocess.Popen(createp12)
    cmd.communicate()
    returncode = cmd.poll()
    if not returncode == 0:
        logger.error("Unable to execute: {0}".format(createp12))
        sys.exit(1)
    logger.info("Creating ambari-keystore.pem for ambari...")
    cmd = subprocess.Popen(createpem)
    cmd.communicate()
    returncode = cmd.poll()
    if not returncode == 0:
        logger.error("Unable to execute: {0}".format(createpem))
        sys.exit(1)
    logger.info("Creating ambari-keystore.crt for ambari...")
    cmd = subprocess.Popen(createcrt)
    cmd.communicate()
    returncode = cmd.poll()
    if not returncode == 0:
        logger.error("Unable to execute: {0}".format(createcrt))
        sys.exit(1)
    return


def read_service_configs(service_name, conf_file):
    ssl_configs = ""
    try:
        os.path.exists(conf_file)
        with open(conf_file) as f:
            config = yaml.safe_load(f)
    except OSError as e:
        logger.error(e)
        return 1
    if service_name in config.keys():
        logger.info("Reading SSL configs for service:{0}".format(service_name))
        ssl_configs = config[service_name]
    else:
        logger.warn("Unable to find SSL configs for: {0} in {1}".format(service_name, conf_file))
        logger.warn("Available configs are: {0}".format(config.keys()))
    #    Consider only installed ranger plugins
    if service_name == "RANGERPLUGINS":
        plugins_to_be_considered = []
        for i in ranger_services_to_be_considered:
            plugins_to_be_considered.append('ranger-'+i.lower()+'-policymgr-ssl')
        for i in ranger_ui_to_be_considered:
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
    if pwd_type is "keyStorePassword":
        password = base64.b64decode(read_conf_file(properties, "caprops", "keyStorePassword"))
    elif pwd_type is "trustStorePassword":
        password = base64.b64decode(read_conf_file(properties, "caprops", "trustStorePassword"))
    return password


def update_configs_ambari(services, accessor, cluster, conf_file):
    config = {}
    for s_name in services.split(','):
        logger.debug("Reading SSL configs from {0}".format(conf_file))
        ssl_configs = read_service_configs(s_name.upper(), conf_file)
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
                elif section[k] == "$historyserver":
                    section[k] = config[0].get("yarn.log.server.url").replace('http:', 'https:').replace('19888', '19890')
                elif section[k] == "$timelineserver":
                    section[k] = config[0].get("yarn.log.server.web-service.url").replace('http:', 'https:').replace('8188', '8190')
                config[0].update({k: section[k]})
            updater = put_configs(config)
            configs.update_config(cluster, config_type, updater, accessor)
            logger.info("Updated configurations for service {0}[{1}]".format(s_name, config_type))
    return


def disable_configs(service, accessor, cluster, conf_file):
    logger.debug("Reading SSL configs from {0}".format(conf_file))
    ssl_configs = read_service_configs(service, conf_file)
    logger.debug("ssl_configs for {0} are {1}".format(service, ssl_configs))

    for section in ssl_configs:
        config_type = section['config_type']
        keys = section.keys()
        del section['config_type']
        if "delete" in keys:
            del section['delete']
            for k in section:
                try:
                    configs.update_config(cluster, config_type, configs.delete_specific_property(k), accessor)
                except Exception:
                    logger.warn("Unable to get/delete configs for config_type:{0} from Ambari".format(config_type))
                    return 1
                logger.info("Disabled SSL for service {0}[{1}]".format(service, config_type))
        else:
            try:
                config = get_configs(accessor, cluster, config_type)
            except Exception:
                logger.warn("Unable to get configs for config_type:{0} from Ambari".format(config_type))
                return 1
            for k in section:
                if section[k] == "$historyserver":
                    section[k] = config[0].get("yarn.log.server.url").replace('https:', 'http:').replace('19890', '19888')
                elif section[k] == "$timelineserver":
                    section[k] = config[0].get("yarn.log.server.web-service.url").replace('https:', 'http:').replace('8190', '8188')
                config[0].update({k: section[k]})
            logger.debug("New configs for {0} are :{1}".format(config_type, json.dumps(config, indent=2)))
            updater = put_configs(config)
            configs.update_config(cluster, config_type, updater, accessor)
            logger.info("Disabled SSL for service {0}[{1}]".format(service, config_type))
    return


def copy_certs(properties, ssh_key, scpusername, ownership):
    opdir = os.path.abspath(read_conf_file(properties, "caprops", "outputDirectory"))
    host_list = read_conf_file(properties, "caprops", "hostnames")
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
        subprocess.Popen(['ssh', '-o', 'StrictHostKeyChecking=no', '-i', ssh_key, userhost, 'chmod', '-R', '750',
                          CERT_DIR]).communicate()
        logger.info("Changing the ownership of certificates..")
        subprocess.Popen(['ssh', '-o', 'StrictHostKeyChecking=no', '-i', ssh_key, userhost, 'chown', '-R', ownership,
                         CERT_DIR]).communicate()
    return


def read_ca_conf_file(properties, section):
    """
    :param properties: property file
    :param section: section name
    :return: Returns the list of key-value pairs in a given section
    """
    ca_props = []
    keypass = keystorepassword
    trustpass = truststorepassword
    if os.path.exists(properties):
        with open(properties) as f:
            ca_config = f.read()
        config = ConfigParser.RawConfigParser()
        config.optionxform = str
        config.readfp(io.BytesIO(ca_config))
        for options in config.options(section):
            ca_props.append("--" + options)
            config.set(section, "keyStorePassword", keypass)
            config.set(section, "trustStorePassword", trustpass)
            ca_props.append(config.get(section, options))
    return ca_props


def read_conf_file(properties, section, key):
    """
    :param properties: property file
    :param section: section name
    :param key: key
    :return: Returns the value of a key in a given section
    """
    value = ""
    if os.path.exists(properties):
        with open(properties) as f:
            ca_config = f.read()
        config = ConfigParser.RawConfigParser()
        config.optionxform = str
        config.readfp(io.BytesIO(ca_config))
        value = config.get(section, key)
    return value


def delete_properties(cluster, config_type, args, accessor):
    logger.info('### Performing "delete":')
    if len(args) == 0:
        logger.error("Not enough arguments. Expected config key.")
        return -1

    config_name = args[0]
    logger.info('### on property "{0}"'.format(config_name))
    configs.update_config(cluster, config_type, configs.delete_specific_property(config_name), accessor)
    return 0


def disable_service(services, cluster, conf_file):
    for servicename in services:
        s_name = servicename.upper()
        logger.info(s_name)
        if s_name == 'ALL':
            for i in services_to_be_considered:
                logger.info("Disabling ssl for {0}".format(i))
                disable_configs(i.upper(), accessor, cluster, conf_file)
        else:
            disable_configs(s_name, accessor, cluster, conf_file)
    return


def disable_ui(uis, cluster, conf_file):
    for uiname in uis:
        u_name = uiname.upper()
        logger.info(u_name)
        if u_name == 'ALL':
            for i in ui_to_be_considered:
                if i == "AMBARIUI":
                    logger.info("Disabling ssl for {0}".format(i))
                    subprocess.Popen(disable_ambari_ui()).communicate()
                elif i == "OOZIE":
                    logger.info("Please follow below instructions to disable SSL for Oozie.")
                    logger.info(DISABLE_OOZIE_UI)
                else:
                    logger.info("Disabling ssl for {0}".format(i))
                    disable_configs(i.upper(), accessor, cluster, conf_file)
        else:
            if u_name == "AMBARIUI":
                subprocess.Popen(disable_ambari_ui()).communicate()
            elif u_name == "OOZIE":
                logger.info("Please follow below instructions to disable SSL for Oozie.")
                logger.info(DISABLE_OOZIE_UI)
            else:
                disable_configs(u_name, accessor, cluster, conf_file)
    return


def parse_service(services, accessor, cluster, conf_file):
    for servicename in services:
        s_name = servicename.upper()
        logger.info(s_name)
        if s_name == 'ALL':
            for i in services_to_be_considered:
                logger.info("Enabling SSL for {0}".format(i))
                update_configs_ambari(i.upper(), accessor, cluster, conf_file)
        else:
            update_configs_ambari(s_name, accessor, cluster, conf_file)
    return


def parse_ui(uis, accessor, cluster, conf_file):
    for uiname in uis:
        u_name = uiname.upper()
        logger.info(u_name)
        if u_name == 'ALL':
            for i in ui_to_be_considered:
                logger.info("Enabling SSL for {0}".format(i))
                if i.upper() == "AMBARIUI":
                    subprocess.Popen(enable_ambari_ui()).communicate()
                elif i.upper() == 'OOZIE':
                    logger.info("Configs to update in {0} are: {1}".format(i.upper(), OOZIE_UI))
                elif i.upper() == 'ATLAS':
                    update_configs_ambari(i.upper(), accessor, cluster, conf_file)
                    logger.info("Perform below operation to enable ssl for {0}: {1}".format(i.upper(), ATLAS_UI))
                else:
                    update_configs_ambari(i.upper(), accessor, cluster, conf_file)

        else:
            if u_name == 'AMBARIUI':
                subprocess.Popen(enable_ambari_ui()).communicate()
                logger.info("Enabling SSL for {0} using : {1}".format(u_name, enable_ambari_ui()))
            elif u_name == 'OOZIE':
                logger.info("Configs to update in {0} are: {1}".format(u_name, OOZIE_UI))
            elif u_name == 'ATLAS':
                update_configs_ambari(u_name, accessor, cluster, conf_file)
                logger.info("Perform below operation to enable ssl for {0}: {1}".format(u_name, ATLAS_UI))
            else:
                logger.info("Enabling SSL for {0}".format(u_name))
                update_configs_ambari(u_name, accessor, cluster, conf_file)
    return


def select_config_file(accessor, conf_type):
    installed_ambari_version = configs.get_ambari_version(accessor).replace('.', '')
    available_config_files = [os.path.basename(x) for x in glob.glob(os.path.join(CA_DIR, CA_CONF_DIR, conf_type+'*'))]
    available_config_versions = [i.replace(conf_type, '').replace('.yaml', '') for i in available_config_files]
    available_config_versions.sort(reverse=True)
    logger.debug("Installed ambari version is: {0}".format(installed_ambari_version))
    logger.debug("Available conf files are: {0}".format(available_config_versions))
    version = compare_versions(available_config_versions, installed_ambari_version)
    conf_file = ""
    if version is not None:
        conf_file = conf_type+str(version)+'.yaml'
        logger.info("Using config file :{0}".format(os.path.join(CA_CONF_DIR, conf_file)))
    else:
        logger.error("Unable to find appropriate config file for version {0}.".format(installed_ambari_version))
        exit(1)
    return conf_file


def compare_versions(available_versions, current_version):
    for x in available_versions:
        if current_version == x:
            version = x
            return version
        elif current_version > x:
            version = x
            return version
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
    parser.add_option("--isOverwrite", action="store_true", default=False, dest="isOverwrite",
                      help="Overwrite existing certificates.")
    parser.add_option("--scpKeyFile", dest="scpKeyFile",
                      help="sshkey to copy the certificates to all the hosts.")
    parser.add_option("--scpUserName", dest="scpUserName",
                      help="username to copy the certificates to all the hosts. Default is current user.", default=os.environ.get('USER'))
    parser.add_option("--crtChown", dest="crtChown",
                      help="Ownership of all the certificates to all the hosts. Default is 'root:hadoop'", default="root:hadoop")
    parser.add_option("--enable-ssl", action="store_true", default=False,
                      dest="enablessl", help="Enables ssl for HDP stack.")
    parser.add_option("--disable-ssl", action="store_true", default=False,
                      dest="disablessl", help="Disables ssl for HDP stack.")
    parser.add_option("--service", help="Comma separated list of services for which SSL "
                                        "needs to be enabled.'all' or comma seperated services. "
                                        "Available configs are: HDFS,MRSHUFFLE,TEZ,HIVE,KAFKA,SPARK,SPARK2,RANGERADMIN,RANGERPLUGINS")
    parser.add_option("--ui", dest="ui", help="Comma separated list of UI's for which SSL needs "
                                              "to be enabled. 'all' or comma seperated uis. "
                                              "Available ui's are: HDFSUI,YARN,MAPREDUCE2UI,HBASE,OOZIE,AMBARI_INFRA,AMBARI_INFRA_SOLR,ATLAS,ZEPPELIN,STORM,AMBARI.")

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
    isoverwrite = options.isOverwrite
    scpkeyfile = options.scpKeyFile
    scpusername = options.scpUserName
    crtchown = options.crtChown
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
    global ranger_ui_to_be_considered
    global ranger_services_to_be_considered

    conf_file_type = ""
    if enable is True:
        conf_file_type = "enable_configs"
    elif disable is True:
        conf_file_type = "disable_configs"
    else:
        logger.error("No config type configured...")
    conf_file = os.path.join(CA_CONF_DIR, select_config_file(accessor, conf_file_type))

    # Getting installed services from ambari and map with the configurable ones.
    installed_services = configs.get_installed_services(cluster, accessor)
    installed_services = installed_services + AMBARI
    if "MAPREDUCE2" in installed_services:
        installed_services.append("MRSHUFFLE")
        installed_services.append("MAPREDUCE2UI")
        installed_services.remove("MAPREDUCE2")
    if "RANGER" in installed_services:
        installed_services.remove("RANGER")
        installed_services = installed_services + RANGER
    if "HDFS" in installed_services:
        installed_services.append("HDFSUI")

    logger.debug("Installed Services/UI's on cluster are: {0}".format(installed_services))
    logger.debug("UI's ssl_manager can configure are: {0}".format(ALL_UI + AMBARI))
    logger.debug("Services ssl_manager can configure are: {0}".format(ALL_SERVICES + RANGER))

    # To Prepare list of installed ranger plugins
    ranger_ui_to_be_considered = list(set(ALL_UI + AMBARI).intersection(installed_services))
    ranger_services_to_be_considered = list(set(ALL_SERVICES + RANGER).intersection(installed_services))

    if disable is True:
        if service is not None:
            if service.upper() != "ALL":
                services = map(str.upper, service.split(','))
                logger.debug("Services passed through cli are: {0}".format(services))
                services_to_be_considered = list(
                    set(ALL_SERVICES+RANGER).intersection(installed_services).intersection(services))
            elif service.upper() == "ALL":
                logger.debug("Services passed through cli are: {0}".format(service))
                services_to_be_considered = list(set(ALL_SERVICES+RANGER).intersection(installed_services))

            if is_hadoop_required(services_to_be_considered, IS_HADOOP) is True:
                services_to_be_considered.append('HADOOP')
            disable_service(services_to_be_considered, cluster, conf_file)

        if ui is not None:
            if ui.upper() != "ALL":
                uis = map(str.upper, ui.split(','))
                logger.debug("UI's passed through cli are: {0}".format(uis))
                ui_to_be_considered = list(set(ALL_UI+AMBARI).intersection(installed_services).intersection(uis))
            elif ui.upper() == "ALL":
                logger.debug("UI's passed through cli are: {0}".format(ui))
                ui_to_be_considered = list(set(ALL_UI+AMBARI).intersection(installed_services))

            if is_hadoop_required(ui_to_be_considered, IS_HADOOP) is True:
                ui_to_be_considered.append('HADOOP')
            disable_ui(ui_to_be_considered, cluster, conf_file)

    elif enable is True:
        global keystorepassword
        keystorepassword = get_password(properties, "keyStorePassword")
        global truststorepassword
        truststorepassword = get_password(properties, "trustStorePassword")

        if ca is True:
            generate_ca(properties, host, isoverwrite)
            if scpkeyfile is not None:
                copy_certs(properties, scpkeyfile, scpusername, crtchown)
            else:
                logger.info(CA)

        if service is not None:
            if service.upper() != "ALL":
                services = map(str.upper, service.split(','))
                logger.debug("Services passed through cli are: {0}".format(services))
                services_to_be_considered = list(
                    set(ALL_SERVICES+RANGER).intersection(installed_services).intersection(services))
            elif service.upper() == "ALL":
                logger.debug("Services passed through cli are: {0}".format(service))
                services_to_be_considered = list(set(ALL_SERVICES+RANGER).intersection(installed_services))

            if is_hadoop_required(services_to_be_considered, IS_HADOOP) is True:
                services_to_be_considered.append('HADOOP')

            logger.info("Services's to enable SSL are {0}".format(services_to_be_considered))
            parse_service(services_to_be_considered, accessor, cluster, conf_file)

        if ui is not None:
            if ui.upper() != "ALL":
                uis = map(str.upper, ui.split(','))
                logger.debug("UI's passed through cli are: {0}".format(uis))
                ui_to_be_considered = list(set(ALL_UI+AMBARI).intersection(installed_services).intersection(uis))
            elif ui.upper() == "ALL":
                logger.debug("UI's passed through cli are: {0}".format(ui))
                ui_to_be_considered = list(set(ALL_UI+AMBARI).intersection(installed_services))

            if is_hadoop_required(ui_to_be_considered, IS_HADOOP) is True:
                ui_to_be_considered.append('HADOOP')

            logger.info("UI's to enable SSL are {0}".format(ui_to_be_considered))
            parse_ui(ui_to_be_considered, accessor, cluster, conf_file)


if __name__ == "__main__":
    try:
        import yaml
    except Exception, e:
        print("\nNeed to install PyYAML package to use yaml. E.g., yum install PyYAML")
        sys.exit(1)
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nAborting ... Keyboard Interrupt.")
        sys.exit(1)

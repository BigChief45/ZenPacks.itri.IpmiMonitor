import logging
log = logging.getLogger('zen.IpmiMonitor.IpmiDataSource')

import subprocess

from twisted.internet.defer import inlineCallbacks, returnValue

from zope.component import adapts
from zope.interface import implements

from Products.ZenEvents import ZenEventClasses
from Products.Zuul.form import schema
from Products.Zuul.infos import ProxyProperty
from Products.Zuul.utils import ZuulMessageFactory as _t

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import (
    PythonDataSource, PythonDataSourcePlugin, PythonDataSourceInfo,
    IPythonDataSourceInfo)

from ZenPacks.itri.IpmiMonitor.lib.ipmitool import parse_ipmi


class IPMIDataSource(PythonDataSource):
    """Data source used to capture data with ipmitool"""

    ZENPACKID = 'ZenPacks.itri.IpmiMonitor'

    sourcetypes = ('IPMI',)
    sourcetype = sourcetypes[0]

    component = '${here/id}'
    cycleTime = 300

    plugin_classname = ZENPACKID + '.datasources.IPMIDataSource.IPMIDataSourcePlugin'

    # Custom fields
    command = ''
    ipAddress = '${dev/manageIp}'
    ipmiUser = '${dev/zIpmiUsername}'
    ipmiPassword = '${dev/zIpmiPassword}'

    _properties = PythonDataSource._properties + (
        {'id': 'command', 'type': 'string', 'mode': 'w'},
        {'id': 'ipAddress', 'type': 'string', 'mode': 'w'},
        {'id': 'ipmiUser', 'type': 'string', 'mode': 'w'},
        {'id': 'ipmiPassword', 'type': 'password', 'mode': 'w'}
    )


class IIPMIDataSourceInfo(IPythonDataSourceInfo):
    """ API Info interface for IIPMIDataSource"""

    command = schema.TextLine(
        title = _t(u'Command'),
        group = _t('IPMI Tool'))
        
    ipAddress = schema.TextLine(
        title = _t(u'IP Address'),
        group = _t('IPMI Tool'))

    ipmiUser = schema.TextLine(
        title = _t(u'IPMI User'),
        group = _t('IPMI Tool'))    

    ipmiPassword = schema.TextLine(
        title = _t(u'IPMI Password'),
        group = _t('IPMI Tool'))

class IPMIDataSourceInfo(PythonDataSourceInfo):
    """API Info adapter factory for IPMIDataSource"""

    implements(IIPMIDataSourceInfo)
    adapts(IPMIDataSource)

    command = ProxyProperty('command')
    ipAddress = ProxyProperty('ipAddress')
    ipmiUser = ProxyProperty('ipmiUser')
    ipmiPassword = ProxyProperty('ipmiPassword')

    cycletime = ProxyProperty('cycletime')

    testable = True


class IPMIDataSourcePlugin(PythonDataSourcePlugin):

    @classmethod
    def config_key(cls, datasource, context):
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.id,
            datasource.plugin_classname,
        )

    @classmethod
    def params(cls, datasource, context):
        return {
            'command': datasource.talesEval(datasource.command, context),
            'ipAddress': datasource.talesEval(datasource.ipAddress, context),
            'ipmiUser': datasource.talesEval(datasource.ipmiUser, context),
            'ipmiPassword': datasource.talesEval(datasource.ipmiPassword, context),
        }        

    @inlineCallbacks
    def collect(self, config):
        log.info('Collect for IPMI data source {0}'.format(config.id))

        data = self.new_data()

        for ds in config.datasources:
            base_cmd = 'ipmitool -H {0} -I lanplus -U {1} -P {2} '.format(
                ds.params['ipAddress'], ds.params['ipmiUser'], ds.params['ipmiPassword'])

            cmd = base_cmd + ds.params['command']
        
            try:
                r = yield subprocess.check_output(cmd, shell=True).rstrip()
            except subprocess.CalledProcessError as e:
                log.error('{0}: {1}'.format(config.id, e))
                returnValue(None)

            # Parse the result
            # Format of ipmitool output is something like:
            #
            # CURRENT | 56h | ok | 7.35 | 8.40 Amps
            #
            # However, the 1st value in lowercase is used as the data point
            # name
            #data['values'][ds.component][ds.datasource] = (5.90, 'N')
            for dp, val in parse_ipmi(r).iteritems():
                dpname = '_'.join((ds.datasource, dp))

                log.debug('{0}: {1}'.format(dpname, val))
                data['values'][None][dpname] = (val, 'N')

        returnValue(data)

    def onSuccess(self, result, config):
        result['events'].append({
            'device': config.id,
            'summary': 'IPMI Collector: Successful collection',
            'severity': ZenEventClasses.Clear,
            'eventKey': 'ipmiCollectionError',
            'eventClassKey': 'ipmiMonitorFailure',
        })
        
        return result

    def onError(self, result, config):
        errmsg = 'Error trying to collect for {1}.{2}'.format(
            config.datasources[0].component, config.datasources[0])
        log.error('{0}: {1}'.format(config.id, errmsg))
        
        data = self.new_data()
        data['events'].append({
            'device': config.id,
            'summary': errmsg,
            'severity': ZenEventClasses.Error,
            'eventKey': 'ipmiCollectionError',            
            'eventClassKey': 'ipmiMonitorFailure',
        })

        return data
from netweaver.plugins.plugin_class import NetWeaverPlugin, NWConnType
from functools import wraps
import logging
from ipaddress import ip_address, IPv4Address, IPv6Address

class CumulusSwitch(NetWeaverPlugin):

	def __init__(self, config, fabricconfig):
		self.is_plugin = True
		self.fabricconfig = fabricconfig
		self.hostname = config['hostname']
		self.username = fabricconfig['credentials']['username']
		self.password = fabricconfig['credentials']['password']
		self.port = 22

		self.build_ssh_session()
		self.cstate = self.pull_state()

	def build_ssh_session(self):
		self.conn_type = NWConnType  #TODO, make this dynamically selected based on something
		self.ssh = self._build_ssh_client(
			hostname=self.hostname,
			username=self.username,
			password=self.password,
			port=self.port
		)

	def get_current_config(self):
		"""
		Get_current_config should return a Dict containing the current state of an object.
		This structure should match the structure of a standard 'role' object.
		"""
		config = {}
		config.update({'hostname': self.get_hostname()})
		return config

	def command(self, command):
		"""
		This just wraps _ssh_command right now, eventually it will allow for other comm types
		:param command:
		:return:
		"""
		if self.ssh:
			return self._ssh_command(command)



	def _net_commit(self):
		ret = self.command('net commit')
		self.cstate = self.pull_state()
		return ret

	def net_config_parser(self):
		pass

	def get_dns_nameservers(self):
		return self.cstate['protocols']['dns']['nameservers']

	def _ifupdown_parser(text):
		# Will parse lines with these keys as interfaces
		iface_keys = ("interface", "iface")
		# Will parse lines starting with these keys as options
		iface_opts = ("address")
		# This variable will be used to remember what interface we are on, in order to place options in the right
		# dict
		ifaces = {}
		current_interface = None
		for line in text.split('\n'):
			# If the line is an interface stanza, this should catch it
			if line.startswith(iface_keys):
				# Split the interface declaration
				line_items = line.split(' ')
				ifname = line_items[1]  # Interface name should be the second item
				ifaces.update({ifname: {}})
				# If there are more than two items on this line, the rest are options
				if len(line_items) > 2:
					opts = line_items[2:len(line_items)]
					ifaces[ifname].update({'options': opts})
				# Any lines starting with an option name from this point on belong to the previously identified interface
				current_interface = ifname
			elif line.strip().startswith(iface_opts):  # Strip whitespace, as the option lines are indented
				opt = line.strip().split(" ")
				# Most options have one value
				if len(opt) == 2:
					ifaces[current_interface].update({opt[0]: opt[1]})
				# But some have more
				if len(opt) > 2:
					ifaces[current_interface].update({opt[0]: []})
					for value in opt[1:len(opt)]:
						ifaces[current_interface][opt[0]].append(value)
		return ifaces

	def pull_state(self):
		commands = self.command('net show configuration commands').split('\n')
		# This dict is constructed following the yaml structure for a role starting at the hostname level
		# Watch the pluralization in here, a lot of the things are unplural in cumulus that are plural in weaver
		conf = {}
		for line in commands:
			# Nameservers
			if line.startswith('net add dns nameserver'):
				try:
					conf['protocols']['dns']['nameservers']
				except KeyError:
					conf.update({'protocols': {'dns': {'nameservers': []}}})
				ln = line.split(' ')
				conf['protocols']['dns']['nameservers'].append(ln[5])
			# Hostname
			elif line.startswith('net add hostname'):
				ln = line.split(' ')
				conf.update({'hostname': ln[3]})
		return conf

	def _check_atrib(self, atrib):
		try:
			atrib
		except KeyError:
			return False
			pass
		else:
			if atrib:
				return True
	def reload_state(self):
		self.cstate = self.pull_state()

	def push_state(self, execute=True):
			queue = []
			dstate = self.appliance.role.config
			if 'hostname' in dstate:
				if dstate['hostname'] != self.cstate['hostname']:
					queue.append(self.set_hostname(dstate['hostname'], execute=False))
			if 'protocols' in dstate:
				if 'dns' in dstate['protocols']:
					if 'nameservers' in dstate['protocols']['dns']:
						if dstate['protocols']['dns']['nameservers'] != self.cstate['protocols']['dns']['nameservers']:
							queue = queue + self.set_dns_nameservers(
								dstate['protocols']['dns']['nameservers'],
								execute=False)
							
			print(queue)
			for com in queue:
				self.command(com)
			self._net_commit()
			self.reload_state()

	def add_dns_nameserver(self, ip, commit=True, execute=True):
		ip = ip_address(ip)
		if ip._version == 4:
			version = 'ipv4'
		elif ip._version == 6:
			version = 'ipv6'
		command = 'net add dns nameserver {} {}'.format(version, ip)
		if execute:
			self.command(command)
			if commit:
				self._net_commit()
		return command

	def get_dns(self):
		return self.cstate['protocols']['dns']

	def set_dns_nameservers(self, nameserverjson, execute=True, commit=True):
		commandqueue = []
		try:
			nslist = self.cstate['protocols']['dns']['nameservers']
		except KeyError:
			pass
		else:
			for ns in nslist:
				if ns not in nameserverjson:
					commandqueue.append(self.rm_dns_nameserver(ns, execute=False))
		for ns in nameserverjson:
				if ns not in self.cstate['protocols']['dns']['nameservers']:
					commandqueue.append(self.add_dns_nameserver(ns, commit=False, execute=False))
		if execute:
			for com in commandqueue:
				self.command(com)
			if commit:
				self._net_commit()
		return commandqueue

	def rm_dns_nameserver(self, ip, commit=True, execute=True):
		ip = ip_address(ip)
		if ip._version == 4:
			version = 'ipv4'
		elif ip._version == 6:
			version = 'ipv6'
		command = 'net del dns nameserver {} {}'.format(version, ip)
		if execute:
			self.command(command)
			if commit:
				self._net_commit()
		return command

	def get_hostname(self):
		return self.command('hostname').strip('\n')

	def set_hostname(self, hostname, execute=True, commit=True):
		command = 'net add hostname {}'.format(hostname)
		if execute:
			self.command(command)
			if commit:
				self._net_commit()
		return command

	def __exit__(self, exc_type, exc_val, exc_tb):
		if self.ssh:
			self.ssh.close()

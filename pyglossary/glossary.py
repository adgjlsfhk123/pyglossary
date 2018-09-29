# -*- coding: utf-8 -*-
# glossary.py
#
# Copyright © 2008-2016 Saeed Rasooli <saeed.gnu@gmail.com> (ilius)
# This file is part of PyGlossary project, https://github.com/ilius/pyglossary
#
# This program is a free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program. Or on Debian systems, from /usr/share/common-licenses/GPL
# If not, see <http://www.gnu.org/licenses/gpl.txt>.

import sys

import os
from os.path import (
	split,
	join,
	splitext,
	isfile,
	isdir,
	dirname,
	basename,
	abspath,
)

from time import time as now
import subprocess
import re

import pkgutil
from collections import Counter
from collections import OrderedDict as odict

import io
from pprint import pformat

from typing import (
	Dict,
	Tuple,
	List,
	Sequence,
	Set,
	Any,
	Optional,
	Union,
	Iterator,
	Iterable,
	ItemsView,
	Callable,
)

from .logger import log
from .flags import *
from . import core
from .core import (
	VERSION,
	rootDir,
	pluginsDir,
	userPluginsDir,
)
from .entry_base import BaseEntry
from .entry import Entry, DataEntry
from .entry_filters_base import EntryFilter
from .sort_stream import hsortStreamList

from .text_utils import (
	fixUtf8,
)
from .os_utils import indir

from .glossary_type import GlossaryType

from .reader_base import BaseReader

homePage = "https://github.com/ilius/pyglossary"

file = io.BufferedReader

try:
	eval("ModuleNotFoundError") # using eval just for mypy
except NameError:
	ModuleNotFoundError = ImportError


def get_ext(path: str) -> str:
	return splitext(path)[1].lower()


class Glossary(GlossaryType):
	"""
	Direct access to glos.data is droped
	Use `glos.addEntry(word, defi, [defiFormat])`
		where both word and defi can be list (including alternates) or string
	See help(glos.addEntry)

	Use `for entry in glos:` to iterate over entries (glossary data)
	See help(pyglossary.entry.Entry) for details

	"""

	# Should be changed according to plugins? FIXME
	infoKeysAliasDict = {
		"title": "name",
		"bookname": "name",
		"dbname": "name",
		##
		"sourcelang": "sourceLang",
		"inputlang": "sourceLang",
		"origlang": "sourceLang",
		##
		"targetlang": "targetLang",
		"outputlang": "targetLang",
		"destlang": "targetLang",
		##
		"license": "copyright",
	}
	plugins = {} # type: Dict[str, Any] # format => pluginModule
	canReadWrite = {} # type: Dict[str, Tuple[bool, bool]]
	readFormats = set() # type: Set[str]
	writeFormats = set() # type: Set[str]
	readFunctions = {} # type: Dict[str, Callable]
	readerClasses = {} # type: Dict[str, BaseReader]
	writeFunctions = {} # type: Dict[str, Callable]
	formatsFilename = {} # type: Dict[str, str]
	formatsByFilename = {} # type: Dict[str, str]
	formatsDesc = {} # type: Dict[str, str]
	formatsExt = {} # type: Dict[str, List[str]]
	formatsReadOptions = {} # type: Dict[str, Any]
	formatsWriteOptions = {} # type: Dict[str, Any]
	readDesc = set() # type: Set[str]
	writeDesc = set() # type: Set[str]
	descFormat = {} # type: Dict[str, str]
	descExt = {} # type: Dict[str, str]
	extFormat = {} # type: Dict[str, str]

	notPluginFilenames = set([
		"formats_common",
		"paths",
		"stardict_tests", # FIXME: move stardict*.py to stardict/
	])

	@classmethod
	def savePluginsJson(cls) -> None:
		import json
		info = {} # type: Dict[str, Dict]
		for name, p in cls.plugins.items():
			canRead, canWrite = cls.canReadWrite[p.format]
			info[name] = {
				"filename": p.filename,
				"enable": p.enable,
				"description": p.description,
				"extentions": p.extentions,
				"canRead": canRead,
				"canWrite": canWrite,
			}
		with open(join(rootDir, "pyglossary", "plugins.json"), "w") as file:
			json.dump(
				info,
				file,
				sort_keys=True,
				indent=2,
				ensure_ascii=True,
			)

	@classmethod
	def loadPluginsJson(cls) -> None:
		import json
		# info = {} # type: Dict[str, Dict[str, Any]]
		with open(join(rootDir, "pyglossary", "plugins.json")) as file:
			info = json.load(file)
		for format, item in info.items():
			filename = item["filename"] # type: str
			desc = item["description"] # type: str
			extentions = item["extentions"] # type: List[str]
			canRead = item["canRead"] # type: bool
			canWrite = item["canWrite"] # type: bool
			cls.descFormat[desc] = format
			cls.descExt[desc] = extentions[0]
			for ext in extentions:
				cls.extFormat[ext] = format
			cls.formatsFilename[format] = filename
			cls.formatsByFilename[filename] = format
			cls.formatsExt[format] = extentions
			cls.formatsDesc[format] = desc
			cls.canReadWrite[format] = (canRead, canWrite)
			if canRead:
				cls.readFormats.add(format)
				cls.readDesc.add(desc)
			if canWrite:
				cls.writeFormats.add(format)
				cls.writeDesc.add(desc)

	@classmethod
	def loadPlugins(cls, directory: str) -> None:
		"""
		executed on startup.  as name implies, loads plugins from directory
		"""
		log.debug("Loading plugins from directory: %r", directory)
		if not isdir(directory):
			log.error("Invalid plugin directory: %r", directory)
			return

		for _, pluginFilename, _ in pkgutil.iter_modules([directory]):
			cls.loadPlugin(directory, pluginFilename)

	@classmethod
	def loadPlugin(cls, directory: str, pluginFilename: str) -> Any:
		sys.path.append(directory)
		try:
			plugin = getattr(__import__(
				"pyglossary.plugins",
				fromlist=[pluginFilename],
			), pluginFilename)
		except Exception as e:
			log.exception("Error while importing plugin %s", pluginFilename)
			raise e
		finally:
			sys.path.pop()

		if (not hasattr(plugin, "enable")) or (not plugin.enable):
			log.warning("Plugin disabled or not a plugin: %s", pluginFilename)
			return

		plugin.filename = pluginFilename

		format = plugin.format

		extentions = plugin.extentions
		# FIXME: deprecate non-tuple values in plugin.extentions
		if isinstance(extentions, str):
			extentions = (extentions,)
		elif not isinstance(extentions, tuple):
			extentions = tuple(extentions)

		if hasattr(plugin, "description"):
			desc = plugin.description
		else:
			desc = "%s (%s)" % (format, extentions[0])

		cls.plugins[format] = plugin
		cls.formatsFilename[format] = pluginFilename
		cls.formatsByFilename[pluginFilename] = format
		cls.descFormat[desc] = format
		cls.descExt[desc] = extentions[0]
		for ext in extentions:
			cls.extFormat[ext] = format
		cls.formatsExt[format] = extentions
		cls.formatsDesc[format] = desc

		hasReadSupport = False
		hasWriteSupport = False

		try:
			Reader = plugin.Reader
		except AttributeError:
			pass
		else:
			if issubclass(Reader, BaseReader):
				cls.readerClasses[format] = Reader
				hasReadSupport = True
			else:
				log.error(
					"Invalid Reader class in \"%s\" plugin, not subclass of BaseReader" % format,
				)

		try:
			cls.readFunctions[format] = plugin.read
		except AttributeError:
			pass
		else:
			hasReadSupport = True

		if hasReadSupport:
			cls.readFormats.add(format)
			cls.readDesc.add(desc)
			cls.formatsReadOptions[format] = getattr(plugin, "readOptions", [])

		if hasattr(plugin, "write"):
			hasWriteSupport = True
			cls.writeFunctions[format] = plugin.write
			cls.writeFormats.add(format)
			cls.writeDesc.add(desc)
			cls.formatsWriteOptions[format] = getattr(
				plugin,
				"writeOptions",
				[]
			)

		cls.canReadWrite[format] = (hasReadSupport, hasWriteSupport)

		return plugin


	@classmethod
	def loadPluginsUnlisted(cls, directory: str) -> None:
		for _, pluginFilename, _ in pkgutil.iter_modules([directory]):
			if pluginFilename in cls.formatsByFilename:
				continue
			if pluginFilename in cls.notPluginFilenames:
				continue
			cls.loadPlugin(directory, pluginFilename)

	@classmethod
	def loadPluginByFormat(cls, format: str) -> None:
		if format in cls.plugins:
			return
		filename = cls.formatsFilename[format]
		#cls.loadPlugin("pyglossary.plugins." + filename)
		cls.loadPlugin(pluginsDir, filename)

	def clear(self) -> None:
		self._info = odict() # type: Dict[str, Any]

		self._data = [] # type: List[Union[Tuple[str, str], Tuple[str, str, str]]]

		readers = self._readers # type: List[BaseReader]
		for reader in readers:
			try:
				reader.close()
			except Exception:
				log.exception("")

		self._readers = [] # type: List[BaseReader]

		self._iter = None # type: Optional[Iterator[BaseEntry]]
		self._entryFilters = [] # type: List[EntryFilter]
		self._sortKey = None # type: Optional[Callable[[str], Any]]
		self._sortCacheSize = 1000

		self._filename = ""
		self._defaultDefiFormat = "m"
		self._progressbar = True

	def __init__(self, info: Optional[Dict[str, str]] = None, ui=Any) -> None:
		"""
		info: OrderedDict instance, or None
			  no need to copy OrderedDict instance,
			  we will not reference to it
		"""
		self._readers = [] # type: List[BaseReader]
		self.clear()
		if info:
			if not isinstance(info, (dict, odict)):
				raise TypeError(
					"Glossary: `info` has invalid type"
					", dict or OrderedDict expected"
				)
			for key, value in info.items():
				self.setInfo(key, value)

		"""
		self._data is a list of tuples with length 2 or 3:
			(word, definition)
			(word, definition, defiFormat)
			where both word and definition can be a string, or list
				(containing word and alternates)

			defiFormat: format of the definition:
				"m": plain text
				"h": html
				"x": xdxf
		"""
		self.ui = ui

	def updateEntryFilters(self) -> None:
		from . import entry_filters as ef
		self._entryFilters = []
		pref = getattr(self.ui, "pref", {})

		self._entryFilters.append(ef.StripEntryFilter(self))
		self._entryFilters.append(ef.NonEmptyWordFilter(self))

		if pref.get("skipResources", False):
			self._entryFilters.append(ef.SkipDataEntryFilter(self))

		if pref.get("utf8Check", True):
			self._entryFilters.append(ef.FixUnicodeFilter(self))

		if pref.get("lower", True):
			self._entryFilters.append(ef.LowerWordFilter(self))

		self._entryFilters.append(ef.LangEntryFilter(self))
		self._entryFilters.append(ef.CleanEntryFilter(self))
		self._entryFilters.append(ef.NonEmptyWordFilter(self))
		self._entryFilters.append(ef.NonEmptyDefiFilter(self))

	def __str__(self) -> str:
		return "glossary.Glossary"

	def addEntryObj(self, entry: BaseEntry) -> None:
		self._data.append(entry.getRaw())

	def newEntry(self, word: str, defi: str, defiFormat: str = "") -> Entry:
		"""
		create and return a new entry object
		"""
		if not defiFormat:
			defiFormat = self._defaultDefiFormat

		return Entry(word, defi, defiFormat)

	def addEntry(self, word: str, defi: str, defiFormat: str = "") -> None:
		"""
		create and add a new entry object to glossary
		"""
		self.addEntryObj(self.newEntry(word, defi, defiFormat))

	def _loadedEntryGen(self) -> Iterator[BaseEntry]:
		wordCount = len(self._data)
		progressbar = self.ui and self._progressbar
		if progressbar:
			self.progressInit("Writing")
		for index, rawEntry in enumerate(self._data):
			yield Entry.fromRaw(
				rawEntry,
				defaultDefiFormat=self._defaultDefiFormat
			)
			if progressbar:
				self.progress(index, wordCount)
		if progressbar:
			self.progressEnd()

	def _readersEntryGen(self) -> Iterator[BaseEntry]:
		for reader in self._readers:
			wordCount = 0
			progressbar = False
			if self.ui and self._progressbar:
				try:
					wordCount = len(reader)
				except Exception:
					log.exception("")
				if wordCount:
					progressbar = True
			if progressbar:
				self.progressInit("Converting")
			try:
				for index, entry in enumerate(reader):
					yield entry
					if progressbar:
						self.progress(index, wordCount)
			finally:
				reader.close()
			if progressbar:
				self.progressEnd()

	def _applyEntryFiltersGen(self, gen: Iterator[BaseEntry]) -> Iterator[BaseEntry]:
		for entry in gen:
			if not entry:
				continue
			for entryFilter in self._entryFilters:
				newEntry = entryFilter.run(entry)
				if not newEntry:
					break
				entry = newEntry
			else:
				yield entry

	def __iter__(self) -> Iterator[BaseEntry]:
		if self._iter is None:
			log.error(
				"Trying to iterate over a blank Glossary"
				", must call `glos.read` first"
			)
			return iter([])
		return self._iter

	def iterEntryBuckets(self, size: int) -> Iterator[List[BaseEntry]]:
		"""
		iterate over buckets of entries, with size `size`
		For example:
			for bucket in glos.iterEntryBuckets(100):
				assert len(bucket) == 100
				for entry in bucket:
					print(entry.getWord())
				print("-----------------")
		"""
		bucket = [] # type: List[BaseEntry]
		for entry in self:
			if len(bucket) >= size:
				yield bucket
				bucket = []
			bucket.append(entry)
		yield bucket

	def setDefaultDefiFormat(self, defiFormat: str) -> None:
		self._defaultDefiFormat = defiFormat

	def getDefaultDefiFormat(self) -> str:
		return self._defaultDefiFormat

	def __len__(self) -> int:
		return len(self._data) + sum(
			len(reader) for reader in self._readers
		)

	def infoKeys(self) -> List[str]:
		return list(self._info.keys())

	def getMostUsedDefiFormats(self, count: int = None) -> List[Tuple[str, int]]:
		return Counter([
			entry.getDefiFormat()
			for entry in self
		]).most_common(count)

	# def formatInfoKeys(self, format: str):# FIXME

	def iterInfo(self) -> ItemsView[str, Any]:
		return self._info.items()

	def getInfo(self, key: str) -> str:
		key = str(key) # FIXME: required?

		try:
			key = self.infoKeysAliasDict[key.lower()]
		except KeyError:
			pass

		return self._info.get(key, "")  # "" or None as default? FIXME

	def setInfo(self, key: str, value: str) -> None:
		#  FIXME
		origKey = key
		key = fixUtf8(key)
		value = fixUtf8(value)

		try:
			key = self.infoKeysAliasDict[key.lower()]
		except KeyError:
			pass

		if origKey != key:
			log.debug("setInfo: %s -> %s", origKey, key)

		self._info[key] = value

	def getExtraInfos(self, excludeKeys: List[str]) -> Dict[str, Any]:
		"""
		excludeKeys: a list of (basic) info keys to be excluded
		returns an OrderedDict including the rest of info keys,
				with associated values
		"""
		excludeKeySet = set()
		for key in excludeKeys:
			excludeKeySet.add(key)
			try:
				excludeKeySet.add(self.infoKeysAliasDict[key.lower()])
			except KeyError:
				pass

		extra = odict() # type: Dict[str, Any]
		for key, value in self._info.items():
			if key in excludeKeySet:
				continue
			extra[key] = value

		return extra

	def getPref(self, name: str, default: Optional[str]) -> Optional[str]:
		if self.ui:
			return self.ui.pref.get(name, default)
		else:
			return default

	def newDataEntry(self, fname: str, data: bytes) -> DataEntry:
		inTmp = not self._readers
		return DataEntry(fname, data, inTmp)

	# ________________________________________________________________________#

	def read(
		self,
		filename: str,
		format: str = "",
		direct: bool = False,
		progressbar: bool = True,
		**options
	) -> bool:
		"""
		filename (str): name/path of input file
		format (str): name of input format,
					  or "" to detect from file extention
		direct (bool): enable direct mode
		"""
		filename = abspath(filename)

		# don't allow direct=False when there are readers
		# (read is called before with direct=True)
		if self._readers and not direct:
			raise ValueError(
				"there are already %s readers" % len(self._readers) +
				", you can not read with direct=False mode"
			)

		self.updateEntryFilters()
		###
		delFile = False
		ext = get_ext(filename)
		if ext in (".gz", ".bz2", ".zip"):
			if ext == ".bz2":
				output, error = subprocess.Popen(
					["bzip2", "-dk", filename],
					stdout=subprocess.PIPE,
				).communicate()
				# -k ==> keep original bz2 file
				# bunzip2 ~= bzip2 -d
				if error:
					log.error(
						error + "\n" +
						"Failed to decompress file \"%s\"" % filename
					)
					return False
				else:
					filename = filename[:-4]
					ext = get_ext(filename)
					delFile = True
			elif ext == ".gz":
				output, error = subprocess.Popen(
					["gzip", "-dc", filename],
					stdout=subprocess.PIPE,
				).communicate()
				# -c ==> write to stdout (we want to keep original gz file)
				# gunzip ~= gzip -d
				if error:
					log.error(
						error + "\n" +
						"Failed to decompress file \"%s\"" % filename
					)
					return False
				else:
					filename = filename[:-3]
					open(filename, "w").write(output)
					ext = get_ext(filename)
					delFile = True
			elif ext == ".zip":
				output, error = subprocess.Popen(
					["unzip", filename, "-d", dirname(filename)],
					stdout=subprocess.PIPE,
				).communicate()
				if error:
					log.error(
						error + "\n" +
						"Failed to decompress file \"%s\"" % filename
					)
					return False
				else:
					filename = filename[:-4]
					ext = get_ext(filename)
					delFile = True
		if not format:
			for key, extList in Glossary.formatsExt.items():
				if ext in extList:
					format = key
			if not format:
				# if delFile:
				#	os.remove(filename)
				log.error("Unknown extension \"%s\" for read support!", ext)

				return False

		Glossary.loadPluginByFormat(format)

		validOptionKeys = self.formatsReadOptions[format]
		for key in list(options.keys()):
			if key not in validOptionKeys:
				log.error(
					"Invalid read option \"%s\" " % key +
					"given for %s format" % format
				)
				del options[key]

		filenameNoExt, ext = splitext(filename)
		if not ext.lower() in self.formatsExt[format]:
			filenameNoExt = filename

		self._filename = filenameNoExt
		if not self.getInfo("name"):
			self.setInfo("name", split(filename)[1])
		self._progressbar = progressbar

		if format in self.readerClasses:
			Reader = self.readerClasses[format]
			reader = Reader(self)
			reader.open(filename, **options)
			if direct:
				self._readers.append(reader)
				log.info(
					"Using Reader class from %s plugin" % format +
					" for direct conversion without loading into memory"
				)
			else:
				self.loadReader(reader)
		else:
			if direct:
				log.warning(
					"No `Reader` class found in %s plugin" % format +
					", falling back to indirect mode"
				)
			result = self.readFunctions[format](
				self,
				filename,
				**options
			)
			# if not result:## FIXME
			#	return False
			if delFile:
				os.remove(filename)

		self._updateIter()

		return True

	def loadReader(self, reader: BaseReader) -> bool:
		"""
		iterates over `reader` object and loads the whole data into self._data
		must call `reader.open(filename)` before calling this function
		"""
		wordCount = 0
		progressbar = False
		if self.ui and self._progressbar:
			try:
				wordCount = len(reader)
			except Exception:
				log.exception("")
			if wordCount:
				progressbar = True
		if progressbar:
			self.progressInit("Reading")
		try:
			for index, entry in enumerate(reader):
				if entry:
					self.addEntryObj(entry)
				if progressbar:
					self.progress(index, wordCount)
		finally:
			reader.close()
		if progressbar:
			self.progressEnd()

		return True

	def _inactivateDirectMode(self) -> None:
		"""
		loads all of `self._readers` into `self._data`
		closes readers
		and sets self._readers to []
		"""
		for reader in self._readers:
			self.loadReader(reader)
		self._readers = [] # type: List[BaseReader]

	def _updateIter(self, sort: bool = False) -> None:
		"""
		updates self._iter
		depending on:
			1- Wheather or not direct mode is On (self._readers not empty)
				or Off (self._readers empty)
			2- Wheather sort is True, and if it is,
				checks for self._sortKey and self._sortCacheSize
		"""
		if self._readers:  # direct mode
			if sort:
				sortKey = self._sortKey
				cacheSize = self._sortCacheSize
				log.info("Stream sorting enabled, cache size: %s", cacheSize)
				# only sort by main word, or list of words + alternates? FIXME
				self._iter = self._applyEntryFiltersGen(iter(hsortStreamList(
					self._readers,
					cacheSize,
					key=Entry.getEntrySortKey(sortKey),
				)))
			else:
				self._iter = self._applyEntryFiltersGen(self._readersEntryGen())
		else:
			self._iter = self._applyEntryFiltersGen(self._loadedEntryGen())

	def sortWords(self, key: Optional[Callable[[str], Any]] = None, cacheSize: int = 0) -> None:
		# only sort by main word, or list of words + alternates? FIXME
		if self._readers:
			self._sortKey = key
			if cacheSize > 0:
				self._sortCacheSize = cacheSize  # FIXME
		else:
			self._data.sort(
				key=Entry.getRawEntrySortKey(key),
			)
		self._updateIter(sort=True)

	def _detectOutput(self, filename: str = "", format: str = "") -> Optional[Tuple[str, str, str]]:
		"""
		returns (filename, format, archiveType) or None
		"""
		archiveType = ""
		if filename:
			ext = ""
			filenameNoExt, fext = splitext(filename)
			fext = fext.lower()
			if fext in (".gz", ".bz2", ".zip"):
				archiveType = fext[1:]
				filename = filenameNoExt
				fext = get_ext(filename)
			if not format:
				for fmt, extList in Glossary.formatsExt.items():
					for e in extList:
						if format == e[1:] or format == e:
							format = fmt
							ext = e
							break
					if format:
						break
				if not format:
					for fmt, extList in Glossary.formatsExt.items():
						if filename == fmt:
							format = filename
							ext = extList[0]
							filename = self._filename + ext
							break
						for e in extList:
							if filename == e[1:] or filename == e:
								format = fmt
								ext = e
								filename = self._filename + ext
								break
						if format:
							break
				if not format:
					for fmt, extList in Glossary.formatsExt.items():
						if fext in extList:
							format = fmt
							ext = fext
			if not format:
				log.error("Unable to detect write format!")
				return None

		else:  # filename is empty
			if not self._filename:
				log.error("Invalid filename %r", filename)
				return None
			filename = self._filename  # no extension
			if not format:
				log.error("No filename nor format is given for output file")
				return None
			try:
				filename += Glossary.formatsExt[format][0]
			except KeyError:
				log.error("Invalid write format")
				return None


		return filename, format, archiveType


	def write(
		self,
		filename: str,
		format: str,
		sort: Optional[bool] = None,
		sortKey: Optional[Callable[[str], Any]] = None,
		sortCacheSize: int = 1000,
		**options
	) -> Optional[str]:
		"""
		sort (bool):
			True (enable sorting),
			False (disable sorting),
			None (auto, get from UI)
		sortKey (callable or None):
			key function for sorting
			takes a word as argument, which is str or list (with alternates)

		returns absolute path of output file, or None if failed
		"""
		if isdir(filename):
			filename = join(filename, basename(self._filename))

		Glossary.loadPluginByFormat(format)

		try:
			validOptionKeys = self.formatsWriteOptions[format]
		except KeyError:
			log.critical("No write support for \"%s\" format", format)
			return None
		for key in list(options.keys()):
			if key not in validOptionKeys:
				log.error(
					"Invalid write option \"%s\"" % key +
					" given for %s format" % format
				)
				del options[key]

		plugin = self.plugins[format]
		sortOnWrite = plugin.sortOnWrite
		if sortOnWrite == ALWAYS:
			if sort is False:
				log.warning(
					"Writing %s requires sorting" % format +
					", ignoring user sort=False option"
				)
			if self._readers:
				log.warning(
					"Writing to %s format requires full sort" % format +
					", falling back to indirect mode"
				)
				self._inactivateDirectMode()
				log.info("Loaded %s entries", len(self._data))
			sort = True
		elif sortOnWrite == DEFAULT_YES:
			if sort is None:
				sort = True
		elif sortOnWrite == DEFAULT_NO:
			if sort is None:
				sort = False
		elif sortOnWrite == NEVER:
			if sort:
				log.warning(
					"Plugin prevents sorting before write" +
					", ignoring user sort=True option"
				)
			sort = False

		if sort:
			if sortKey is None:
				try:
					sortKey = plugin.sortKey
				except AttributeError:
					pass
				else:
					log.debug(
						"Using sort key function from %s plugin" % format
					)
			elif sortOnWrite == ALWAYS:
				try:
					sortKey = plugin.sortKey
				except AttributeError:
					pass
				else:
					log.warning(
						"Ignoring user-defined sort order, " +
						"and using key function from %s plugin" % format
					)
			self.sortWords(
				key=sortKey,
				cacheSize=sortCacheSize
			)
		else:
			self._updateIter(sort=False)

		filename = abspath(filename)
		log.info("Writing to file \"%s\"", filename)
		try:
			self.writeFunctions[format](self, filename, **options)
		except Exception:
			log.exception("Exception while calling plugin\'s write function")
			return None
		finally:
			self.clear()

		return filename

	def archiveOutDir(self, filename: str, archiveType: str) -> str:
		"""
		filename is the existing file path
		archiveType is the archive extention (without dot): "gz", "bz2", "zip"
		"""
		try:
			os.remove("%s.%s" % (filename, archiveType))
		except OSError:
			pass
		if archiveType == "gz":
			output, error = subprocess.Popen(
				["gzip", filename],
				stdout=subprocess.PIPE,
			).communicate()
			if error:
				log.error(
					error + "\n" +
					"Failed to compress file \"%s\"" % filename
				)
		elif archiveType == "bz2":
			output, error = subprocess.Popen(
				["bzip2", filename],
				stdout=subprocess.PIPE,
			).communicate()
			if error:
				log.error(
					error + "\n" +
					"Failed to compress file \"%s\"" % filename
				)
		elif archiveType == "zip":
			dirn, name = split(filename)
			with indir(dirn):
				output, error = subprocess.Popen(
					["zip", filename+".zip", name, "-m"],
					stdout=subprocess.PIPE,
				).communicate()
				if error:
					log.error(
						error + "\n" +
						"Failed to compress file \"%s\"" % filename
					)
		archiveFilename = "%s.%s" % (filename, archiveType)
		if isfile(archiveFilename):
			return archiveFilename
		else:
			return filename

	def convert(
		self,
		inputFilename: str,
		inputFormat: str = "",
		direct: Optional[bool] = None,
		progressbar: bool = True,
		outputFilename: str = "",
		outputFormat: str = "",
		sort: Optional[bool] = None,
		sortKey: Optional[Callable[[str], Any]] = None,
		sortCacheSize: int = 1000,
		readOptions: Optional[Dict[str, Any]] = None,
		writeOptions: Optional[Dict[str, Any]] = None,
	) -> Optional[str]:
		"""
		returns absolute path of output file, or None if failed
		"""
		if not readOptions:
			readOptions = {}
		if not writeOptions:
			writeOptions = {}

		outputArgs = self._detectOutput(
			filename=outputFilename,
			format=outputFormat,
		)
		if not outputArgs:
			log.error("Writing file \"%s\" failed.", outputFilename)
			return None
		outputFilename, outputFormat, archiveType = outputArgs

		if direct is None:
			if sort is not True:
				direct = True  # FIXME
			else:
				direct = False

		tm0 = now()
		if not self.read(
			inputFilename,
			format=inputFormat,
			direct=direct,
			progressbar=progressbar,
			**readOptions
		):
			return None
		log.info("")

		finalOutputFile = self.write(
			outputFilename,
			outputFormat,
			sort=sort,
			sortKey=sortKey,
			sortCacheSize=sortCacheSize,
			**writeOptions
		)
		log.info("")
		if not finalOutputFile:
			log.error("Writing file \"%s\" failed.", outputFilename)
			return None

		if archiveType:
			finalOutputFile = self.archiveOutDir(finalOutputFile, archiveType)

		log.info("Writing file \"%s\" done.", finalOutputFile)
		log.info("Running time of convert: %.1f seconds", now() - tm0)

		return finalOutputFile

	# ________________________________________________________________________#

	def writeTxt(
		self,
		sep1: str,
		sep2: str,
		filename: str = "",
		writeInfo: bool = True,
		rplList: Optional[Sequence[Tuple[str, str]]] = None,
		ext: str = ".txt",
		head: str = "",
		iterEntries: Optional[Iterator[BaseEntry]] = None,
		entryFilterFunc: Optional[Callable[[BaseEntry], Optional[BaseEntry]]] = None,
		outInfoKeysAliasDict: Optional[Dict[str, str]] = None,
		encoding: str = "utf-8",
		newline: str = "\n",
		resources: bool = True,
	) -> bool:
		if rplList is None:
			rplList = []
		if not filename:
			filename = self._filename + ext
		if not outInfoKeysAliasDict:
			outInfoKeysAliasDict = {}

		fp = open(filename, "w", encoding=encoding, newline=newline)
		fp.write(head)
		if writeInfo:
			for key, desc in self._info.items():
				try:
					key = outInfoKeysAliasDict[key]
				except KeyError:
					pass
				for rpl in rplList:
					desc = desc.replace(rpl[0], rpl[1])
				fp.write("##" + key + sep1 + desc + sep2)
		fp.flush()

		myResDir = filename + "_res"
		if not isdir(myResDir):
			os.mkdir(myResDir)

		if not iterEntries:
			iterEntries = iter(self)

		for entry in iterEntries:
			if entry.isData():
				if resources:
					entry.save(myResDir)

			if entryFilterFunc:
				newEntry = entryFilterFunc(entry)
				if not newEntry:
					continue
				entry = newEntry 

			word = entry.getWord()
			defi = entry.getDefi()
			if word.startswith("#"):  # FIXME
				continue
			# if self.getPref("enable_alts", True):  # FIXME

			for rpl in rplList:
				defi = defi.replace(rpl[0], rpl[1])
			fp.write(word + sep1 + defi + sep2)
		fp.close()
		if not os.listdir(myResDir):
			os.rmdir(myResDir)
		return True

	def writeTabfile(self, filename: str = "", **kwargs) -> None:
		self.writeTxt(
			"\t",
			"\n",
			filename=filename,
			rplList=(
				("\\", "\\\\"),
				("\n", "\\n"),
				("\t", "\\t"),
			),
			ext=".txt",
			**kwargs
		)

	def writeDict(self, filename: str = "", writeInfo: bool = False) -> None:
		# Used in "/usr/share/dict/" for some dictionarys such as "ding"
		self.writeTxt(
			" :: ",
			"\n",
			filename,
			writeInfo,
			(
				("\n", "\\n"),
			),
			".dict",
		)

	def iterSqlLines(
		self,
		filename: str = "",
		infoKeys: Optional[List] = None,
		addExtraInfo: bool = True,
		newline: str = "\\n",
		transaction: bool = False,
	) -> Iterator[str]:
		newline = "<br>"
		infoDefLine = "CREATE TABLE dbinfo ("
		infoValues = []

		if not infoKeys:
			infoKeys = [
				"dbname",
				"author",
				"version",
				"direction",
				"origLang",
				"destLang",
				"license",
				"category",
				"description",
			]

		for key in infoKeys:
			value = self.getInfo(key)
			value = value.replace("\'", "\'\'")\
						 .replace("\x00", "")\
						 .replace("\r", "")\
						 .replace("\n", newline)
			infoValues.append("\'" + value + "\'")
			infoDefLine += "%s char(%d), " % (key, len(value))

		infoDefLine = infoDefLine[:-2] + ");"
		yield infoDefLine

		if addExtraInfo:
			yield (
				"CREATE TABLE dbinfo_extra (" +
				"\'id\' INTEGER PRIMARY KEY NOT NULL, " +
				"\'name\' TEXT UNIQUE, \'value\' TEXT);"
			)

		yield (
			"CREATE TABLE word (\'id\' INTEGER PRIMARY KEY NOT NULL, " +
			"\'w\' TEXT, \'m\' TEXT);"
		)

		if transaction:
			yield "BEGIN TRANSACTION;"
		yield "INSERT INTO dbinfo VALUES(%s);" % (",".join(infoValues))

		if addExtraInfo:
			extraInfo = self.getExtraInfos(infoKeys)
			for index, (key, value) in enumerate(extraInfo.items()):
				yield (
					"INSERT INTO dbinfo_extra " +
					"VALUES(%d, \'%s\', \'%s\');" % (
						index + 1,
						key.replace("\'", "\'\'"),
						value.replace("\'", "\'\'"),
					)
				)

		for i, entry in enumerate(self):
			if entry.isData():
				# FIXME
				continue
			word = entry.getWord()
			defi = entry.getDefi()
			word = word.replace("\'", "\'\'")\
				.replace("\r", "").replace("\n", newline)
			defi = defi.replace("\'", "\'\'")\
				.replace("\r", "").replace("\n", newline)
			yield "INSERT INTO word VALUES(%d, \'%s\', \'%s\');" % (
				i+1,
				word,
				defi,
			)
		if transaction:
			yield "END TRANSACTION;"
		yield "CREATE INDEX ix_word_w ON word(w COLLATE NOCASE);"

	# ________________________________________________________________________#

	def takeOutputWords(self, minWordLen: int = 3) -> List[str]:
		wordPattern = re.compile("[\w]{%d,}" % minWordLen, re.U)
		words = set()
		progressbar, self._progressbar = self._progressbar, False
		for entry in self:
			words.update(re.findall(
				wordPattern,
				entry.getDefi(),
			))
		self._progressbar = progressbar
		return sorted(words)

	# ________________________________________________________________________#

	def progressInit(self, *args) -> None:
		if self.ui:
			self.ui.progressInit(*args)

	def progress(self, wordI: int, wordCount: int) -> None:
		if self.ui and wordI % (wordCount//500 + 1) == 0:
			self.ui.progress(
				min(wordI + 1, wordCount) / wordCount,
				"%d / %d completed" % (wordI, wordCount),
			)

	def progressEnd(self) -> None:
		if self.ui:
			self.ui.progressEnd()

	# ________________________________________________________________________#

	def searchWordInDef(
		self,
		st: str,
		matchWord: bool = True,
		sepChars: str = ".,،",
		maxNum: int = 100,
		minRel: float = 0.0,
		minWordLen: int = 3,
		includeDefs: bool = False,
		showRel: str = "Percent", # "Percent" | "Percent At First" | ""
	) -> List[str]:
		# searches word "st" in definitions of the glossary
		splitPattern = re.compile(
			"|".join([re.escape(x) for x in sepChars]),
			re.U,
		)
		wordPattern = re.compile("[\w]{%d,}" % minWordLen, re.U)
		outRel = [] # type: List[Tuple]
		for item in self._data:
			words, defi = item[:2]
			if isinstance(words, str):
				words = [words]
			if isinstance(defi, list):
				defi = "\n".join(defi)
			if st not in defi:
				continue
			for word in words:
				rel = 0.0  # relation value of word (0 <= rel <= 1)
				for part in re.split(splitPattern, defi):
					if not part:
						continue
					if matchWord:
						partWords = re.findall(
							wordPattern,
							part,
						)
						if not partWords:
							continue
						rel = max(
							rel,
							partWords.count(st) / len(partWords)
						)
					else:
						rel = max(
							rel,
							part.count(st) * len(st) / len(part)
						)
				if rel <= minRel:
					continue
				if includeDefs:
					outRel.append((word, rel, defi))
				else:
					outRel.append((word, rel))
		outRel.sort(
			key=lambda x: x[1],
			reverse=True,
		)
		n = len(outRel)
		if n > maxNum > 0:
			outRel = outRel[:maxNum]
			n = maxNum
		num = 0
		out = []
		if includeDefs:
			for j in range(n):
				numP = num
				w, num, m = outRel[j]
				m = m.replace("\n", "\\n").replace("\t", "\\t")
				onePer = int(1.0/num)
				if onePer == 1.0:
					out.append("%s\\n%s" % (w, m))
				elif showRel == "Percent":
					out.append("%s(%%%d)\\n%s" % (w, 100*num, m))
				elif showRel == "Percent At First":
					if num == numP:
						out.append("%s\\n%s" % (w, m))
					else:
						out.append("%s(%%%d)\\n%s" % (w, 100*num, m))
				else:
					out.append("%s\\n%s" % (w, m))
			return out
		for j in range(n):
			numP = num
			w, num = outRel[j]
			onePer = int(1.0/num)
			if onePer == 1.0:
				out.append(w)
			elif showRel == "Percent":
				out.append("%s(%%%d)" % (w, 100*num))
			elif showRel == "Percent At First":
				if num == numP:
					out.append(w)
				else:
					out.append("%s(%%%d)" % (w, 100*num))
			else:
				out.append(w)
		return out

	def reverse(
		self,
		savePath: str = "",
		words: Optional[List[str]] = None,
		includeDefs: bool = False,
		reportStep: int = 300,
		saveStep: int = 1000,  # set this to zero to disable auto saving
		**kwargs
	) -> Iterator[int]:
		"""
		This is a generator
		Usage:
			for wordIndex in glos.reverse(...):
				pass

		Inside the `for` loop, you can pause by waiting (for input or a flag)
			or stop by breaking

		Potential keyword arguments:
			words = None ## None, or list
			reportStep = 300
			saveStep = 1000
			savePath = ""
			matchWord = True
			sepChars = ".,،"
			maxNum = 100
			minRel = 0.0
			minWordLen = 3
			includeDefs = False
			showRel = "None"
				allowed values: "None", "Percent", "Percent At First"
		"""
		if not savePath:
			savePath = self.getInfo("name") + ".txt"

		if saveStep < 2:
			raise ValueError("saveStep must be more than 1")

		ui = self.ui

		if words:
			words = list(words)
		else:
			words = self.takeOutputWords()

		wordCount = len(words)
		log.info(
			"Reversing to file \"%s\"" % savePath +
			", number of words: %s" % wordCount
		)
		self.progressInit("Reversing")
		with open(savePath, "w") as saveFile:
			for wordI in range(wordCount):
				word = words[wordI]
				self.progress(wordI, wordCount)

				if wordI % saveStep == 0 and wordI > 0:
					saveFile.flush()
				result = self.searchWordInDef(
					word,
					includeDefs=includeDefs,
					**kwargs
				)
				if result:
					try:
						if includeDefs:
							defi = "\\n\\n".join(result)
						else:
							defi = ", ".join(result) + "."
					except Exception:
						log.exception("")
						log.debug("result = " + pformat(result))
						return
					saveFile.write("%s\t%s\n" % (word, defi))
				yield wordI

		self.progressEnd()
		yield wordCount


#Glossary.loadPlugins(pluginsDir)
Glossary.loadPluginsJson()
Glossary.loadPluginsUnlisted(pluginsDir)
Glossary.loadPlugins(userPluginsDir)
#Glossary.savePluginsJson()

#!/usr/bin/env python3

"""Model description

Model description is the representation of the various externals
included in the model. It processes in input data structure, and
converts it into a standard interface that is used by the rest of the
system.

To maintain backward compatibility, externals description files should
follow semantic versioning rules, http://semver.org/



"""
from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function

import logging
import os
import os.path
import re
from configparser import ConfigParser as config_parser
from configparser import MissingSectionHeaderError
from configparser import NoSectionError, NoOptionError

from .utils import printlog, fatal_error, str_to_bool, expand_local_url
from .utils import execute_subprocess
from .global_constants import EMPTY_STR, PPRINTER, VERSION_SEPERATOR

#
# Globals
#
DESCRIPTION_SECTION = "externals_description"
VERSION_ITEM = "schema_version"


def read_externals_description_file(root_dir, file_name):
    """Read a file containing an externals description and
    create its internal representation.

    """
    root_dir = os.path.abspath(root_dir)
    msg = f"In directory : {root_dir}"
    logging.info(msg)
    printlog("Processing externals description file : {file_name}")

    file_path = os.path.join(root_dir, file_name)
    if not os.path.exists(file_name):
        if file_name.lower() == "none":
            msg = (
                "INTERNAL ERROR: Attempt to read externals file "
                f"from {file_path} when not configured"
            )
        else:
            msg = (
                f'ERROR: Model description file, "{file_name}", does not '
                f"exist at path:\n    {file_path}\nDid you run from the root of "
                "the source tree?"
            )

        fatal_error(msg)

    externals_description = None
    if file_name == ExternalsDescription.GIT_SUBMODULES_FILENAME:
        externals_description = read_gitmodules_file(root_dir, file_name)
    else:
        try:
            config = config_parser()
            config.read(file_path)
            externals_description = config
        except MissingSectionHeaderError:
            # not a cfg file
            pass

    if externals_description is None:
        msg = "Unknown file format!"
        fatal_error(msg)

    return externals_description


class LstripReader(object):
    "LstripReader formats .gitmodules files to be acceptable for configparser"

    def __init__(self, filename):
        with open(filename, "r", encoding="utf-8") as infile:
            lines = infile.readlines()
        self._lines = []
        self._num_lines = len(lines)
        self._index = 0
        for line in lines:
            self._lines.append(line.lstrip())

    def readlines(self):
        """Return all the lines from this object's file"""
        return self._lines

    def readline(self, size=-1):
        """Format and return the next line or raise StopIteration"""
        try:
            line = self.next()
        except StopIteration:
            line = ""

        if (size > 0) and (len(line) < size):
            return line[0:size]

        return line

    def __iter__(self):
        """Begin an iteration"""
        self._index = 0
        return self

    def next(self):
        """Return the next line or raise StopIteration"""
        if self._index >= self._num_lines:
            raise StopIteration

        self._index = self._index + 1
        return self._lines[self._index - 1]

    def __next__(self):
        return self.next()


def git_submodule_status(repo_dir):
    """Run the git submodule status command to obtain submodule hashes."""
    # This function is here instead of GitRepository to avoid a dependency loop
    cwd = os.getcwd()
    os.chdir(repo_dir)
    cmd = ["git", "submodule", "status"]
    git_output = execute_subprocess(cmd, output_to_caller=True)
    submodules = {}
    submods = git_output.split("\n")
    for submod in submods:
        if submod:
            status = submod[0]
            items = submod[1:].split(" ")
            if len(items) > 2:
                tag = items[2]
            else:
                tag = None

            submodules[items[1]] = {"hash": items[0], "status": status, "tag": tag}

    os.chdir(cwd)
    return submodules


def parse_submodules_desc_section(section_items, file_path):
    """Find the path and url for this submodule description"""
    path = None
    url = None
    for item in section_items:
        name = item[0].strip()
        if name == "path":
            path = item[1].strip()
        elif name == "url":
            url = item[1].strip()
        elif name == "branch":
            # We do not care about branch since we have a hash - silently ignore
            pass
        else:
            msg = "WARNING: Ignoring unknown {} property, in {}"
            msg = msg.format(item[0], file_path)  # fool pylint
            logging.warning(msg)

    return path, url


def read_gitmodules_file(root_dir, file_name):
    """Read a .gitmodules file and convert it to be compatible with an
    externals description.
    """
    # pylint: disable=too-many-locals
    root_dir = os.path.abspath(root_dir)
    msg = f"In directory : {root_dir}"
    logging.info(msg)
    printlog(f"Processing submodules description file : {file_name}")

    file_path = os.path.join(root_dir, file_name)
    if not os.path.exists(file_name):
        msg = (
            f'ERROR: submodules description file, "{file_name}", does not '
            f"exist at path:\n    {file_path}"
        )
        fatal_error(msg)

    submodules_description = None
    externals_description = None
    try:
        config = config_parser()
        config.read_file(LstripReader(file_path), source=file_name)

        submodules_description = config
    except MissingSectionHeaderError:
        # not a cfg file
        pass

    if submodules_description is None:
        msg = "Unknown file format!"
        fatal_error(msg)
    else:
        # Convert the submodules description to an externals description
        externals_description = config_parser()
        # We need to grab all the commit hashes for this repo
        submods = git_submodule_status(root_dir)
        for section in submodules_description.sections():
            if section[0:9] == "submodule":
                sec_name = section[9:].strip(' "')
                externals_description.add_section(sec_name)
                section_items = submodules_description.items(section)
                path, url = parse_submodules_desc_section(section_items, file_path)

                if path is None:
                    msg = f"Submodule {sec_name} missing path"
                    fatal_error(msg)

                if url is None:
                    msg = f"Submodule {sec_name} missing url"
                    fatal_error(msg)

                externals_description.set(sec_name, ExternalsDescription.PATH, path)
                externals_description.set(
                    sec_name, ExternalsDescription.PROTOCOL, "git"
                )
                externals_description.set(sec_name, ExternalsDescription.REPO_URL, url)
                externals_description.set(
                    sec_name, ExternalsDescription.REQUIRED, "True"
                )
                if sec_name in submods:
                    submod_name = sec_name
                else:
                    # The section name does not have to match the path
                    submod_name = path

                if submod_name in submods:
                    git_hash = submods[submod_name]["hash"]
                    externals_description.set(
                        sec_name, ExternalsDescription.HASH, git_hash
                    )
                else:
                    emsg = (
                        f"submodule status has no section, '{submod_name}'"
                        "\nCheck section names in externals config file"
                    )
                    fatal_error(emsg)

        # Required items
        externals_description.add_section(DESCRIPTION_SECTION)
        externals_description.set(DESCRIPTION_SECTION, VERSION_ITEM, "1.0.0")

    return externals_description


def create_externals_description(
    model_data, model_format="cfg", components=None, exclude=None, parent_repo=None
):
    """Create the a externals description object from the provided data"""
    externals_description = None
    if model_format == "dict":
        externals_description = ExternalsDescriptionDict(
            model_data, components=components, exclude=exclude
        )
    elif model_format == "cfg":
        major, _, _ = get_cfg_schema_version(model_data)
        if major == 1:
            externals_description = ExternalsDescriptionConfigV1(
                model_data,
                components=components,
                exclude=exclude,
                parent_repo=parent_repo,
            )
        else:
            msg = (
                "Externals description file has unsupported schema "
                f'version "{major}".'
            )
            fatal_error(msg)
    else:
        msg = f'Unknown model data format "{model_format}"'
        fatal_error(msg)
    return externals_description


def get_cfg_schema_version(model_cfg):
    """Extract the major, minor, patch version of the config file schema

    Params:
    model_cfg - config parser object containing the externas description data

    Returns:
    major = integer major version
    minor = integer minor version
    patch = integer patch version
    """
    semver_str = ""
    try:
        semver_str = model_cfg.get(DESCRIPTION_SECTION, VERSION_ITEM)
    except (NoSectionError, NoOptionError):
        msg = (
            "externals description file must have the required "
            f'section: "{DESCRIPTION_SECTION}" and item "{VERSION_ITEM}"'
        )
        fatal_error(msg)

    # NOTE(bja, 2017-11) Assume we don't care about the
    # build/pre-release metadata for now!
    version_list = re.split(r"[-+]", semver_str)
    version_str = version_list[0]
    version = version_str.split(VERSION_SEPERATOR)
    try:
        major = int(version[0].strip())
        minor = int(version[1].strip())
        patch = int(version[2].strip())
    except ValueError:
        msg = (
            "Config file schema version must have integer digits for "
            "major, minor and patch versions. "
            f'Received "{version_str}"'
        )
        fatal_error(msg)
    return major, minor, patch


class ExternalsDescription(dict):
    """Base externals description class that is independent of the user input
    format. Different input formats can all be converted to this
    representation to provide a consistent represtentation for the
    rest of the objects in the system.

    NOTE(bja, 2018-03): do NOT define _schema_major etc at the class
    level in the base class. The nested/recursive nature of externals
    means different schema versions may be present in a single run!

    All inheriting classes must overwrite:
        self._schema_major and self._input_major
        self._schema_minor and self._input_minor
        self._schema_patch and self._input_patch

    where _schema_x is the supported schema, _input_x is the user
    input value.

    """

    # keywords defining the interface into the externals description data
    EXTERNALS = "externals"
    BRANCH = "branch"
    SUBMODULE = "from_submodule"
    HASH = "hash"
    NAME = "name"
    PATH = "local_path"
    PROTOCOL = "protocol"
    REPO = "repo"
    REPO_URL = "repo_url"
    REQUIRED = "required"
    TAG = "tag"
    SPARSE = "sparse"

    PROTOCOL_EXTERNALS_ONLY = "externals_only"
    PROTOCOL_GIT = "git"
    PROTOCOL_SVN = "svn"
    GIT_SUBMODULES_FILENAME = ".gitmodules"
    KNOWN_PRROTOCOLS = [PROTOCOL_GIT, PROTOCOL_SVN, PROTOCOL_EXTERNALS_ONLY]

    # v1 xml keywords
    _V1_TREE_PATH = "TREE_PATH"
    _V1_ROOT = "ROOT"
    _V1_TAG = "TAG"
    _V1_BRANCH = "BRANCH"
    _V1_REQ_SOURCE = "REQ_SOURCE"

    _source_schema = {
        REQUIRED: True,
        PATH: "string",
        EXTERNALS: "string",
        SUBMODULE: True,
        REPO: {
            PROTOCOL: "string",
            REPO_URL: "string",
            TAG: "string",
            BRANCH: "string",
            HASH: "string",
            SPARSE: "string",
        },
    }

    def __init__(self, parent_repo=None):
        """Convert the xml into a standardized dict that can be used to
        construct the source objects

        """
        dict.__init__(self)
        self._schema_major = None
        self._schema_minor = None
        self._schema_patch = None
        self._input_major = None
        self._input_minor = None
        self._input_patch = None
        self._parent_repo = parent_repo

    def _verify_schema_version(self):
        """Use semantic versioning rules to verify we can process this schema."""
        known = f"{self._schema_major}.{self._schema_minor}.{self._schema_patch}"
        received = f"{self._input_major}.{self._input_minor}.{self._input_patch}"

        if self._input_major != self._schema_major:
            # should never get here, the factory should handle this correctly!
            msg = (
                f'DEV_ERROR: version "{known}" parser received '
                f'version "{received}" input.'
            )
            fatal_error(msg)

        if self._input_minor > self._schema_minor:
            msg = (
                "Incompatible schema version:\n"
                f'  User supplied schema version "{received}" is too new."\n'
                f'  Can only process version "{known}" files and '
                "older."
            )
            fatal_error(msg)

        if self._input_patch > self._schema_patch:
            # NOTE(bja, 2018-03) ignoring for now... Not clear what
            # conditions the test is needed.
            pass

    def _check_user_input(self):
        """Run a series of checks to attempt to validate the user input and
        detect errors as soon as possible.

        NOTE(bja, 2018-03) These checks are called *after* the file is
        read. That means the schema check can not occur here.

        Note: the order is important. check_optional will create
        optional with null data. run check_data first to ensure
        required data was provided correctly by the user.

        """
        self._check_data()
        self._check_optional()
        self._validate()

    def _check_data(self):
        # pylint: disable=too-many-branches,too-many-statements
        """Check user supplied data is valid where possible."""
        for ext_name in list(self.keys()):
            if self[ext_name][self.REPO][self.PROTOCOL] not in self.KNOWN_PRROTOCOLS:
                msg = (
                    "Unknown repository protocol "
                    f'"{self[ext_name][self.REPO][self.PROTOCOL]}" in "{ext_name}".'
                )
                fatal_error(msg)

            if self[ext_name][self.REPO][self.PROTOCOL] == self.PROTOCOL_SVN:
                if self.HASH in self[ext_name][self.REPO]:
                    msg = (
                        f'In repo description for "{ext_name}". svn repositories '
                        'may not include the "hash" keyword.'
                    )
                    fatal_error(msg)

            if (self[ext_name][self.REPO][self.PROTOCOL] != self.PROTOCOL_GIT) and (
                self.SUBMODULE in self[ext_name]
            ):
                msg = (
                    f"self.SUBMODULE is only supported with {self.PROTOCOL_GIT} protocol, "
                    f'"{ext_name}" is defined as an '
                    f"{self[ext_name][self.REPO][self.PROTOCOL]} repository"
                )
                fatal_error(msg)

            if self[ext_name][self.REPO][self.PROTOCOL] != self.PROTOCOL_EXTERNALS_ONLY:
                ref_count = 0
                found_refs = ""
                if self.TAG in self[ext_name][self.REPO]:
                    ref_count += 1
                    found_refs = (
                        f'"{self.TAG} = '
                        f'"{self[ext_name][self.REPO][self.TAG]}", {found_refs}'
                    )
                if self.BRANCH in self[ext_name][self.REPO]:
                    ref_count += 1
                    found_refs = (
                        f'"{self.BRANCH} = '
                        '{self[ext_name][self.REPO][self.BRANCH]}", {found_refs}'
                    )
                if self.HASH in self[ext_name][self.REPO]:
                    ref_count += 1
                    found_refs = (
                        f'"{self.HASH} = '
                        '{self[ext_name][self.REPO][self.HASH]}", {found_refs}'
                    )
                if self.SUBMODULE in self[ext_name] and self[ext_name][self.SUBMODULE]:
                    ref_count += 1
                    found_refs = (
                        f'"{self.SUBMODULE} = '
                        '{self[ext_name][self.SUBMODULE]}", {found_refs}'
                    )
                if ref_count > 1:
                    msg = "Model description is over specified! "
                    if self.SUBMODULE in self[ext_name]:
                        msg += (
                            "from_submodule is not compatible with "
                            '"tag", "branch", or "hash" '
                        )
                    else:
                        msg += (
                            ' Only one of "tag", "branch", or "hash" '
                            "may be specified "
                        )

                    msg += f'for repo description of "{ext_name}".'.format(ext_name)
                    msg += f"\nFound: {found_refs}"
                    fatal_error(msg)
                elif ref_count < 1:
                    msg = (
                        "Model description is under specified! One of "
                        '"tag", "branch", or "hash" must be specified for '
                        f'repo description of "{ext_name}"'
                    )
                    fatal_error(msg)

                if self.REPO_URL not in self[ext_name][self.REPO] and (
                    self.SUBMODULE not in self[ext_name]
                    or not self[ext_name][self.SUBMODULE]
                ):
                    msg = (
                        "Model description is under specified! Must have "
                        '"repo_url" in repo '
                        f'description for "{ext_name}"'
                    )
                    fatal_error(msg)

                if self.SUBMODULE in self[ext_name] and self[ext_name][self.SUBMODULE]:
                    if self.REPO_URL in self[ext_name][self.REPO]:
                        msg = (
                            "Model description is over specified! "
                            "from_submodule keyword is not compatible "
                            f"with {self.REPO_URL} keyword for"
                        )
                        msg += f' repo description of "{ext_name}"'
                        fatal_error(msg)

                    if self.PATH in self[ext_name]:
                        msg = (
                            "Model description is over specified! "
                            "from_submodule keyword is not compatible with "
                            f"{self.PATH} keyword for"
                        )
                        msg += f' repo description of "{ext_name}"'
                        fatal_error(msg)

                if self.REPO_URL in self[ext_name][self.REPO]:
                    url = expand_local_url(
                        self[ext_name][self.REPO][self.REPO_URL], ext_name
                    )
                    self[ext_name][self.REPO][self.REPO_URL] = url

    def _check_optional(self):
        # pylint: disable=too-many-branches
        """Some fields like externals, repo:tag repo:branch are
        (conditionally) optional. We don't want the user to be
        required to enter them in every externals description file, but
        still want to validate the input. Check conditions and add
        default values if appropriate.

        """
        submod_desc = None  # Only load submodules info once
        for field in self:
            # truely optional
            if self.EXTERNALS not in self[field]:
                self[field][self.EXTERNALS] = EMPTY_STR

            # git and svn repos must tags and branches for validation purposes.
            if self.TAG not in self[field][self.REPO]:
                self[field][self.REPO][self.TAG] = EMPTY_STR
            if self.BRANCH not in self[field][self.REPO]:
                self[field][self.REPO][self.BRANCH] = EMPTY_STR
            if self.HASH not in self[field][self.REPO]:
                self[field][self.REPO][self.HASH] = EMPTY_STR
            if self.REPO_URL not in self[field][self.REPO]:
                self[field][self.REPO][self.REPO_URL] = EMPTY_STR
            if self.SPARSE not in self[field][self.REPO]:
                self[field][self.REPO][self.SPARSE] = EMPTY_STR

            # from_submodule has a complex relationship with other fields
            if self.SUBMODULE in self[field]:
                # User wants to use submodule information, is it available?
                if self._parent_repo is None:
                    # No parent == no submodule information
                    PPRINTER.pprint(self[field])
                    msg = f'No parent submodule for "{field}"'
                    fatal_error(msg)
                elif self._parent_repo.protocol() != self.PROTOCOL_GIT:
                    PPRINTER.pprint(self[field])
                    msg = (
                        f'Parent protocol, "{self._parent_repo.protocol()}"'
                        ", does not support submodules"
                    )
                    fatal_error(msg)
                else:
                    args = self._repo_config_from_submodule(field, submod_desc)
                    repo_url, repo_path, ref_hash, submod_desc = args

                    if repo_url is None:
                        msg = (
                            f'Cannot checkout "{field}" as a submodule, '
                            f"repo not found in {self.GIT_SUBMODULES_FILENAME} file"
                        )
                        fatal_error(msg)
                    # Fill in submodule fields
                    self[field][self.REPO][self.REPO_URL] = repo_url
                    self[field][self.REPO][self.HASH] = ref_hash
                    self[field][self.PATH] = repo_path

                if self[field][self.SUBMODULE]:
                    # We should get everything from the parent submodule
                    # configuration.
                    pass
                # No else (from _submodule = False is the default)
            else:
                # Add the default value (not using submodule information)
                self[field][self.SUBMODULE] = False

    def _repo_config_from_submodule(self, field, submod_desc):
        """Find the external config information for a repository from
        its submodule configuration information.
        """
        if submod_desc is None:
            repo_path = os.getcwd()  # Is this always correct?
            submod_file = self._parent_repo.submodules_file(repo_path=repo_path)
            if submod_file is None:
                msg = (
                    f'Cannot checkout "{field}" from submodule information\n'
                    f'       Parent repo, "{self._parent_repo.name()}" does not have submodules'
                )
                fatal_error(msg)
            submod_file = read_gitmodules_file(repo_path, submod_file)
            submod_desc = create_externals_description(submod_file)

        # Can we find our external?
        repo_url = None
        repo_path = None
        ref_hash = None
        for ext_field in submod_desc:
            if field == ext_field:
                ext = submod_desc[ext_field]
                repo_url = ext[self.REPO][self.REPO_URL]
                repo_path = ext[self.PATH]
                ref_hash = ext[self.REPO][self.HASH]
                break

        return repo_url, repo_path, ref_hash, submod_desc

    def _validate(self):
        """Validate that the parsed externals description contains all necessary
        fields.

        """

        def print_compare_difference(data_a, data_b, loc_a, loc_b):
            """Look through the data structures and print the differences."""
            for item in data_a:
                if item in data_b:
                    if not isinstance(data_b[item], type(data_a[item])):
                        printlog(
                            f"    {item}: {loc_a} = {data_a[item]} ({type(data_a[item])})"
                        )
                        whitespace = " " * len(item)
                        printlog(
                            f"    {whitespace}  {loc_b} = {data_b[item]} ({type(data_b[item])})"
                        )
                else:
                    printlog(
                        f"    {item}: {loc_a} = {data_a[item]} ({type(data_a[item])})"
                    )
                    whitespace = " " * len(item)
                    printlog(f"    {whitespace}  {loc_b} missing")

        def validate_data_struct(schema, data):
            """Compare a data structure against a schema and validate all required
            fields are present.

            """
            is_valid = False
            in_ref = True
            valid = True
            if isinstance(schema, dict) and isinstance(data, dict):
                # Both are dicts, recursively verify that all fields
                # in schema are present in the data.
                for key in schema:
                    in_ref = in_ref and (key in data)
                    if in_ref:
                        valid = valid and (validate_data_struct(schema[key], data[key]))

                is_valid = in_ref and valid
            else:
                # non-recursive structure. verify data and schema have
                # the same type.
                is_valid = isinstance(data, type(schema))

            if not is_valid:
                printlog("  Unmatched schema and input:")
                if isinstance(schema, dict):
                    print_compare_difference(schema, data, "schema", "input")
                    print_compare_difference(data, schema, "input", "schema")
                else:
                    printlog(f"    schema = {schema} ({type(schema)})")
                    printlog(f"    input = {data} ({type(data)})")

            return is_valid

        for field in self:
            valid = validate_data_struct(self._source_schema, self[field])
            if not valid:
                PPRINTER.pprint(self._source_schema)
                PPRINTER.pprint(self[field])
                msg = f'ERROR: source for "{field}" did not validate'
                fatal_error(msg)


class ExternalsDescriptionDict(ExternalsDescription):
    """Create a externals description object from a dictionary using the API
    representations. Primarily used to simplify creating model
    description files for unit testing.

    """

    def __init__(self, model_data, components=None, exclude=None):
        """Parse a native dictionary into a externals description."""
        ExternalsDescription.__init__(self)
        self._schema_major = 1
        self._schema_minor = 0
        self._schema_patch = 0
        self._input_major = 1
        self._input_minor = 0
        self._input_patch = 0
        self._verify_schema_version()
        if components:
            for key in list(model_data.keys()):
                if key not in components:
                    del model_data[key]

        if exclude:
            for key in list(model_data.keys()):
                if key in exclude:
                    del model_data[key]

        self.update(model_data)
        self._check_user_input()


class ExternalsDescriptionConfigV1(ExternalsDescription):
    """Create a externals description object from a config_parser object,
    schema version 1.

    """

    def __init__(self, model_data, components=None, exclude=None, parent_repo=None):
        """Convert the config data into a standardized dict that can be used to
        construct the source objects

        """
        ExternalsDescription.__init__(self, parent_repo=parent_repo)
        self._schema_major = 1
        self._schema_minor = 1
        self._schema_patch = 0
        (
            self._input_major,
            self._input_minor,
            self._input_patch,
        ) = get_cfg_schema_version(model_data)
        self._verify_schema_version()
        self._remove_metadata(model_data)
        self._parse_cfg(model_data, components=components, exclude=exclude)
        self._check_user_input()

    @staticmethod
    def _remove_metadata(model_data):
        """Remove the metadata section from the model configuration file so
        that it is simpler to look through the file and construct the
        externals description.

        """
        model_data.remove_section(DESCRIPTION_SECTION)

    def _parse_cfg(self, cfg_data, components=None, exclude=None):
        """Parse a config_parser object into a externals description."""

        def list_to_dict(input_list, convert_to_lower_case=True):
            """Convert a list of key-value pairs into a dictionary."""
            output_dict = {}
            for item in input_list:
                key = item[0].strip()
                value = item[1].strip()
                if convert_to_lower_case:
                    key = key.lower()
                output_dict[key] = value
            return output_dict

        for section in cfg_data.sections():
            name = section.strip()
            if (components and name not in components) or (exclude and name in exclude):
                continue
            self[name] = {}
            self[name].update(list_to_dict(cfg_data.items(section)))
            self[name][self.REPO] = {}
            loop_keys = self[name].copy().keys()
            for item in loop_keys:
                if item in self._source_schema:
                    if isinstance(self._source_schema[item], bool):
                        self[name][item] = str_to_bool(self[name][item])
                elif item in self._source_schema[self.REPO]:
                    self[name][self.REPO][item] = self[name][item]
                    del self[name][item]
                else:
                    msg = f'Invalid input: "{name}" contains unknown ' f'item "{item}".'
                    fatal_error(msg)

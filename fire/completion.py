# Copyright (C) 2018 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Provides tab completion functionality for CLIs built with Fire."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import copy
import inspect

from fire import inspectutils


def Script(name, component, default_options=None, shell='bash'):
  if shell == 'fish':
    return _FishScript(name, _Commands(component), default_options)
  return _BashScript(name, _Commands(component), default_options)


def _BashScript(name, commands, default_options=None):
  """Returns a Bash script registering a completion function for the commands.

  Args:
    name: The first token in the commands, also the name of the command.
    commands: A list of all possible commands that tab completion can complete
        to. Each command is a list or tuple of the string tokens that make up
        that command.
    default_options: A dict of options that can be used with any command. Use
        this if there are flags that can always be appended to a command.
  Returns:
    A string which is the Bash script. Source the bash script to enable tab
    completion in Bash.
  """
  default_options = default_options or set()
  global_options, options_map, subcommands_map = _GetMaps(
      name, commands, default_options
  )

  bash_completion_template = """# bash completion support for {name}
# DO NOT EDIT.
# This script is autogenerated by fire/completion.py.

_complete-{identifier}()
{{
  local cur prev opts lastcommand
  COMPREPLY=()
  prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  lastcommand=$(get_lastcommand)

  opts="{default_options}"
  GLOBAL_OPTIONS="{global_options}"

{checks}

  COMPREPLY=( $(compgen -W "${{opts}}" -- ${{cur}}) )
  return 0
}}

get_lastcommand()
{{
  local lastcommand i

  lastcommand=
  for ((i=0; i < ${{#COMP_WORDS[@]}}; ++i)); do
    if [[ ${{COMP_WORDS[i]}} != -* ]] && [[ -n ${{COMP_WORDS[i]}} ]] && [[
      ${{COMP_WORDS[i]}} != $cur ]]; then
      lastcommand=${{COMP_WORDS[i]}}
    fi
  done

  echo $lastcommand
}}

filter_options()
{{
  local opts
  opts=""
  for opt in "$@"
  do
    if ! option_already_entered $opt; then
      opts="$opts $opt"
    fi
  done

  echo $opts
}}

option_already_entered()
{{
  local opt
  for opt in ${{COMP_WORDS[@]:0:$COMP_CWORD}}
  do
    if [ $1 == $opt ]; then
      return 0
    fi
  done
  return 1
}}

is_prev_global()
{{
  local opt
  for opt in $GLOBAL_OPTIONS
  do
    if [ $opt == $prev ]; then
      return 0
    fi
  done
  return 1
}}

complete -F _complete-{identifier} {command}
"""

  check_wrapper = """
  case "${{lastcommand}}" in
  {lastcommand_checks}
  esac"""

  lastcommand_check_template = """
    {command})
      {opts_assignment}
      opts=$(filter_options $opts)
    ;;"""

  opts_assignment_subcommand_template = """
      if is_prev_global; then
        opts="${{GLOBAL_OPTIONS}}"
      else
        opts="{options} ${{GLOBAL_OPTIONS}}"
      fi"""

  opts_assignment_main_command_template = """
      opts="{options} ${{GLOBAL_OPTIONS}}" """

  def _GetOptsAssignmentTemplate(command):
    if command == name:
      return opts_assignment_main_command_template
    else:
      return opts_assignment_subcommand_template

  lines = []
  commands_set = set()
  commands_set.add(name)
  commands_set = commands_set.union(set(subcommands_map.keys()))
  commands_set = commands_set.union(set(options_map.keys()))
  for command in commands_set:
    opts_assignment = _GetOptsAssignmentTemplate(command).format(
        options=' '.join(
            sorted(options_map[command].union(subcommands_map[command]))
        ),
    )
    lines.append(
        lastcommand_check_template.format(
            command=command,
            opts_assignment=opts_assignment)
    )
  lastcommand_checks = '\n'.join(lines)

  checks = check_wrapper.format(
      lastcommand_checks=lastcommand_checks,
  )

  return (
      bash_completion_template.format(
          name=name,
          command=name,
          checks=checks,
          default_options=' '.join(default_options),
          identifier=name.replace('/', '').replace('.', '').replace(',', ''),
          global_options=' '.join(global_options),
      )
  )


def _FishScript(name, commands, default_options=None):
  """Returns a Fish script registering a completion function for the commands.

  Args:
    name: The first token in the commands, also the name of the command.
    commands: A list of all possible commands that tab completion can complete
        to. Each command is a list or tuple of the string tokens that make up
        that command.
    default_options: A dict of options that can be used with any command. Use
        this if there are flags that can always be appended to a command.
  Returns:
    A string which is the Fish script. Source the fish script to enable tab
    completion in Fish.
  """
  default_options = default_options or set()
  global_options, options_map, subcommands_map = _GetMaps(
      name, commands, default_options
  )

  fish_source = """function __fish_using_command
    set cmd (commandline -opc)
    for i in (seq (count $cmd) 1)
        switch $cmd[$i]
        case "-*"
        case "*"
            if [ $cmd[$i] = $argv[1] ]
                return 0
            else
                return 1
            end
        end
    end
    return 1
end

function __option_entered_check
    set cmd (commandline -opc)
    for i in (seq (count $cmd))
        switch $cmd[$i]
        case "-*"
            if [ $cmd[$i] = $argv[1] ]
                return 1
            end
        end
    end
    return 0
end

function __is_prev_global
    set cmd (commandline -opc)
    set global_options {global_options}
    set prev (count $cmd)

    for opt in $global_options
        if [ "--$opt" = $cmd[$prev] ]
            echo $prev
            return 0
        end
    end
    return 1
end

"""

  subcommand_template = ("complete -c {name} -n '__fish_using_command "
                         "{command}' -f -a {subcommand}\n")
  flag_template = ("complete -c {name} -n "
                   "'__fish_using_command {command};{prev_global_check} and "
                   "__option_entered_check --{option}' -l {option}\n")

  prev_global_check = ' and __is_prev_global;'
  for command in set(subcommands_map.keys()).union(set(options_map.keys())):
    for subcommand in subcommands_map[command]:
      fish_source += subcommand_template.format(
          name=name,
          command=command,
          subcommand=subcommand,
      )

    for option in options_map[command].union(global_options):
      check_needed = command != name
      fish_source += flag_template.format(
          name=name,
          command=command,
          prev_global_check=prev_global_check if check_needed else '',
          option=option.lstrip('--'),
      )

  return fish_source.format(
      global_options=' '.join(f'"{option}"' for option in global_options)
  )


def MemberVisible(component, name, member, class_attrs=None, verbose=False):
  """Returns whether a member should be included in auto-completion or help.

  Determines whether a member of an object with the specified name should be
  included in auto-completion or help text(both usage and detailed help).

  If the member name starts with '__', it will always be excluded. If it
  starts with only one '_', it will be included for all non-string types. If
  verbose is True, the members, including the private members, are included.

  When not in verbose mode, some modules and functions are excluded as well.

  Args:
    component: The component containing the member.
    name: The name of the member.
    member: The member itself.
    class_attrs: (optional) If component is a class, provide this as:
      inspectutils.GetClassAttrsDict(component). If not provided, it will be
      computed.
    verbose: Whether to include private members.
  Returns
    A boolean value indicating whether the member should be included.
  """
  if isinstance(name, str) and name.startswith('__'):
    return False
  if verbose:
    return True
  if (member is absolute_import
      or member is division
      or member is print_function):
    return False
  if isinstance(member, type(absolute_import)):
    return False
  # TODO(dbieber): Determine more generally which modules to hide.
  modules_to_hide = []
  if inspect.ismodule(member) and member in modules_to_hide:
    return False
  if inspect.isclass(component):
    # If class_attrs has not been provided, compute it.
    if class_attrs is None:
      class_attrs = inspectutils.GetClassAttrsDict(component) or {}
    class_attr = class_attrs.get(name)
    if class_attr:
      # Methods and properties should only be accessible on instantiated
      # objects, not on uninstantiated classes.
      if class_attr.kind in ('method', 'property'):
        return False
      # Backward compatibility notes: Before Python 3.8, namedtuple attributes
      # were properties. In Python 3.8, they have type tuplegetter.
      tuplegetter = getattr(collections, '_tuplegetter', type(None))
      if isinstance(class_attr.object, tuplegetter):
        return False
  if isinstance(name, str):
    return not name.startswith('_')
  return True  # Default to including the member


def VisibleMembers(component, class_attrs=None, verbose=False):
  """Returns a list of the members of the given component.

  If verbose is True, then members starting with _ (normally ignored) are
  included.

  Args:
    component: The component whose members to list.
    class_attrs: (optional) If component is a class, you may provide this as:
      inspectutils.GetClassAttrsDict(component). If not provided, it will be
      computed. If provided, this determines how class members will be treated
      for visibility. In particular, methods are generally hidden for
      non-instantiated classes, but if you wish them to be shown (e.g. for
      completion scripts) then pass in a different class_attr for them.
    verbose: Whether to include private members.
  Returns:
    A list of tuples (member_name, member) of all members of the component.
  """
  if isinstance(component, dict):
    members = component.items()
  else:
    members = inspect.getmembers(component)

  # If class_attrs has not been provided, compute it.
  if class_attrs is None:
    class_attrs = inspectutils.GetClassAttrsDict(component)
  return [
      (member_name, member) for member_name, member in members
      if MemberVisible(component, member_name, member, class_attrs=class_attrs,
                       verbose=verbose)
  ]


def _CompletionsFromArgs(fn_args):
  """Takes a list of fn args and returns a list of the fn's completion strings.

  Args:
    fn_args: A list of the args accepted by a function.
  Returns:
    A list of possible completion strings for that function.
  """
  completions = []
  for arg in fn_args:
    arg = arg.replace('_', '-')
    completions.append(f'--{arg}')
  return completions


def Completions(component, verbose=False):
  """Gives possible Fire command completions for the component.

  A completion is a string that can be appended to a command to continue that
  command. These are used for TAB-completions in Bash for Fire CLIs.

  Args:
    component: The component whose completions to list.
    verbose: Whether to include all completions, even private members.
  Returns:
    A list of completions for a command that would so far return the component.
  """
  if inspect.isroutine(component) or inspect.isclass(component):
    spec = inspectutils.GetFullArgSpec(component)
    return _CompletionsFromArgs(spec.args + spec.kwonlyargs)

  if isinstance(component, (tuple, list)):
    return [str(index) for index in range(len(component))]

  if inspect.isgenerator(component):
    # TODO(dbieber): There are currently no commands available for generators.
    return []

  return [
      _FormatForCommand(member_name)
      for member_name, _ in VisibleMembers(component, verbose=verbose)
  ]


def _FormatForCommand(token):
  """Replaces underscores with hyphens, unless the token starts with a token.

  This is because we typically prefer hyphens to underscores at the command
  line, but we reserve hyphens at the start of a token for flags. This becomes
  relevant when --verbose is activated, so that things like __str__ don't get
  transformed into --str--, which would get confused for a flag.

  Args:
    token: The token to transform.
  Returns:
    The transformed token.
  """
  if not isinstance(token, str):
    token = str(token)

  if token.startswith('_'):
    return token

  return token.replace('_', '-')


def _Commands(component, depth=3):
  """Yields tuples representing commands.

  To use the command from Python, insert '.' between each element of the tuple.
  To use the command from the command line, insert ' ' between each element of
  the tuple.

  Args:
    component: The component considered to be the root of the yielded commands.
    depth: The maximum depth with which to traverse the member DAG for commands.
  Yields:
    Tuples, each tuple representing one possible command for this CLI.
    Only traverses the member DAG up to a depth of depth.
  """
  if inspect.isroutine(component) or inspect.isclass(component):
    for completion in Completions(component, verbose=False):
      yield (completion,)
  if inspect.isroutine(component):
    return  # Don't descend into routines.

  if depth < 1:
    return

  # By setting class_attrs={} we don't hide methods in completion.
  for member_name, member in VisibleMembers(component, class_attrs={},
                                            verbose=False):
    # TODO(dbieber): Also skip components we've already seen.
    member_name = _FormatForCommand(member_name)

    yield (member_name,)

    for command in _Commands(member, depth - 1):
      yield (member_name,) + command


def _IsOption(arg):
  return arg.startswith('-')


def _GetMaps(name, commands, default_options):
  """Returns sets of subcommands and options for each command.

  Args:
    name: The first token in the commands, also the name of the command.
    commands: A list of all possible commands that tab completion can complete
        to. Each command is a list or tuple of the string tokens that make up
        that command.
    default_options: A dict of options that can be used with any command. Use
        this if there are flags that can always be appended to a command.
  Returns:
    global_options: A set of all options of the first token of the command.
    subcommands_map: A dict storing set of subcommands for each
        command/subcommand.
    options_map: A dict storing set of options for each subcommand.
  """
  global_options = copy.copy(default_options)
  options_map = collections.defaultdict(lambda: copy.copy(default_options))
  subcommands_map = collections.defaultdict(set)

  for command in commands:
    if len(command) == 1:
      if _IsOption(command[0]):
        global_options.add(command[0])
      else:
        subcommands_map[name].add(command[0])

    elif command:
      subcommand = command[-2]
      arg = _FormatForCommand(command[-1])

      if _IsOption(arg):
        args_map = options_map
      else:
        args_map = subcommands_map

      args_map[subcommand].add(arg)
      args_map[subcommand.replace('_', '-')].add(arg)

  return global_options, options_map, subcommands_map

# Vision

Every coding agent is a CLI with a config directory. Organizations should be able to run any of
them, today's and tomorrow's, through one API, safely, without harness engineering, and keep the
harness as a package they own. The platform is the execution layer and nothing more: it runs a
package in a sandbox it owns against a provider the tenant brings, returns what the package decided,
and keeps the record. Agents, loops, benchmarks and harnesses built on harnesses are programs
against that API, written by the people who need them.

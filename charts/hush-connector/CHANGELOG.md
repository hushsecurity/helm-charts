<!-- markdownlint-configure-file { "MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

## hush-connector 0.1.0 - 2026-10-21

### Added

- initial release of the Hush Security Connector chart. It installs the
  connector on its own, the same pod the `hush-sensor` chart deploys under
  `connector.*`, and takes its credentials the same way.

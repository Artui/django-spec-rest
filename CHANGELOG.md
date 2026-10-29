# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This package continues `djangorestframework-services`, whose history it
carries; releases up to 0.62.0 are in
[that package's changelog](https://github.com/Artui/djangorestframework-services/blob/main/CHANGELOG.md).

## [Unreleased]

### Changed

- **Renamed from `djangorestframework-services`.** The distribution is
  `django-spec-rest` and the importable package is `django_spec_rest`, where it
  was `rest_framework_services`; every module keeps its path under the new
  root. Replace the import prefix and the dependency name; nothing else about
  the API changes in this step.

### Removed

- **The `startserviceapp` management command** and its app template. The layout
  it scaffolded was a convention rather than anything the package reads, so a
  project lays out its services, selectors and validators as it likes.
- **The package is no longer a Django app.** With the command gone it has no
  models, migrations, templates, static files or URLs, so it needs no
  `INSTALLED_APPS` entry: remove `"rest_framework_services"` from the setting
  rather than renaming it.

[Unreleased]: https://github.com/Artui/django-spec-rest/compare/v0.0.0...HEAD

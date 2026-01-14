### Do
- default to small components. prefer focused modules over god components
- default to small files and diffs. avoid repo wide rewrites unless asked
- Where appropriate and possible, add color and design options in `app/static/*.css`
- Add detailed inline documentation to any added functions, classes, or methods.


### Don't
- do not hard code colors
- do not use `div`s if we have a component already
- do not add new heavy dependencies without approval

### Safety and permissions
Allowed without prompt:
- read files, list files
- tsc single file, prettier, eslint,
- vitest single test

Ask first: 
- package installs,
- git push
- deleting files, chmod
- running full build or end to end suites

### Project structure
- see `routes.py` for routes
- templates live in `app/templates`
- static assets are in `app/static`

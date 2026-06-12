module github.com/kiff/kiff-guard-cookbook/refund-ceiling-guard/kiff-decide

go 1.23.0

// kiffhq/kiff (NOT kiff/kiff) is intentional: a version-bound module path.
// v0.2.0 — the proven version — is published under github.com/kiffhq/kiff;
// the framework moved to github.com/kiff/kiff only at v0.4.0. Do not
// blanket-rename to kiff/kiff (it breaks the build). v0.4.0 migration is
// tracked debt: it changes the permission model and needs re-validation.
require github.com/kiffhq/kiff v0.2.0

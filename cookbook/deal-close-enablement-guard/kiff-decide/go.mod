module github.com/kiff/kiff-guard-cookbook/deal-close-enablement-guard/kiff-decide

go 1.23.0

// Latest framework release: github.com/kiff/kiff v0.6.0. The module moved
// from github.com/kiffhq/kiff to github.com/kiff/kiff at v0.4.0, and role
// membership became policy-owned (AssignRole) at the same time — actor.Roles
// no longer carries authority (#19). NewPermissionPolicy reflects that.
require github.com/kiff/kiff v0.6.0

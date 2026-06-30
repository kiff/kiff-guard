module github.com/kiff/kiff-guard-cookbook/payment-recovery-enablement-guard/kiff-decide

go 1.23.0

// Latest framework release: github.com/kiff/kiff v0.6.0. Role membership is
// policy-owned (AssignRole) since v0.4.0 — actor.Roles no longer carries
// authority (#19). NewPermissionPolicy reflects that.
require github.com/kiff/kiff v0.6.0

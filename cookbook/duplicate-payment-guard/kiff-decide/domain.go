// Package main is the KIFF decide server for the duplicate-payment-guard
// cookbook recipe. It wraps the real KIFF runtime with a tiny payments
// domain and exposes the decide contract the guard SDK speaks.
//
// The domain is the whole point of the recipe: an Invoice moves
// PENDING -> PAID, and PAY_INVOICE is allowed ONLY from PENDING. So the
// first payment clears and advances the state; every retry hits a PAID
// invoice and KIFF returns state_not_allowed. The state machine — not a
// dedupe table in the app — is what enforces "pay once."
package main

import (
	"context"
	"fmt"
	"time"

	"github.com/kiff/kiff/pkg/kiff/action"
	"github.com/kiff/kiff/pkg/kiff/actor"
	"github.com/kiff/kiff/pkg/kiff/adapter"
	"github.com/kiff/kiff/pkg/kiff/domain"
	"github.com/kiff/kiff/pkg/kiff/event"
	"github.com/kiff/kiff/pkg/kiff/permission"
	"github.com/kiff/kiff/pkg/kiff/runtime"
)

const (
	AdapterAP = "ap"

	EntityInvoice = "Invoice"

	EventInvoiceReceived = "INVOICE_RECEIVED"
	EventInvoicePaid     = "INVOICE_PAID"

	StatePending = "PENDING"
	StatePaid    = "PAID"

	ActionPayInvoice = "PAY_INVOICE"

	PermPayInvoice permission.Permission = "ap.pay_invoice"
)

// AgentActor is the AP agent. Roles carry the pay permission; the real
// trust boundary (roles from the authenticated key, not the body) is the
// cloud's job — here the standalone server trusts its own configured
// actor so the recipe stays single-binary.
var AgentActor = actor.Actor{
	ID:          "ap-agent",
	Type:        actor.TypeAgent,
	DisplayName: "AP Agent",
	Roles:       []string{"ap_agent"},
}

// NewDomainDefinition builds the payments domain. The load-bearing line
// is Allow(StatePending, ActionPayInvoice): PAY_INVOICE is meaningful
// only while the invoice is PENDING. Once INVOICE_PAID advances it to
// PAID, the same action is state_not_allowed.
func NewDomainDefinition() (domain.Definition, error) {
	b := domain.New("ap-payments").
		Entity(EntityInvoice).
		Event(EventInvoiceReceived).
		Event(EventInvoicePaid).
		Transition(EventInvoiceReceived, "", StatePending).
		Transition(EventInvoicePaid, StatePending, StatePaid).
		Allow(StatePending, ActionPayInvoice).
		Action(payInvoiceContract())
	return b.Build()
}

// payInvoiceContract declares PAY_INVOICE: allowed only in PENDING,
// requires the amount + an idempotency-relevant invoice id, needs the
// ap.pay_invoice permission, high risk. No approval requirement — the
// point of this recipe is that the STATE MACHINE stops the duplicate,
// not an approval gate. The executor is a no-op: execution (the real
// debit) lives in the ap-app, not in KIFF (KIFF governs; the app acts).
func payInvoiceContract() action.ActionContract {
	return action.ActionContract{
		Name:                ActionPayInvoice,
		AllowedStates:       []string{StatePending},
		RequiredParameters:  []string{"amount_cents"},
		RequiredPermissions: []permission.Permission{PermPayInvoice},
		Risk:                action.RiskHigh,
		ApprovalRequirement: action.ApprovalNever,
		Executor: func(_ context.Context, ctx action.ActionContext) (action.ActionResult, error) {
			// KIFF cleared it; the app performs the debit. KIFF only
			// records that the action was permitted. We do NOT emit
			// INVOICE_PAID here — the app ingests it after a real
			// debit, so the state only advances on a real side effect.
			return action.ActionResult{
				ActionName:     ActionPayInvoice,
				EntityID:       ctx.EntityID,
				Status:         action.ExecutionSucceeded,
				Executed:       true,
				Message:        "cleared to pay; app performs the debit",
				EffectsSummary: "payment cleared",
				ExecutedAt:     time.Now().UTC(),
			}, nil
		},
	}
}

func NewPermissionPolicy() *permission.SimplePolicy {
	p := permission.NewSimplePolicy()
	p.GrantRole("ap_agent", PermPayInvoice)
	p.GrantRole("system", PermPayInvoice)
	return p
}

func NewInputAdapter() (adapter.Adapter, error) {
	return adapter.NewPassthroughAdapter(AdapterAP)
}

func NewRuntime() (*runtime.Runtime, error) {
	def, err := NewDomainDefinition()
	if err != nil {
		return nil, err
	}
	in, err := NewInputAdapter()
	if err != nil {
		return nil, err
	}
	return runtime.NewForDomain(def, runtime.Config{
		PermissionPolicy: NewPermissionPolicy(),
		Adapters:         []adapter.Adapter{in},
	})
}

func invoiceEvent(invoiceID, eventType, actorID string, payload map[string]any) event.Event {
	return event.Event{
		ID:         fmt.Sprintf("evt-%s-%s-%d", eventType, invoiceID, time.Now().UnixNano()),
		Type:       eventType,
		EntityID:   invoiceID,
		EntityType: EntityInvoice,
		Source:     "ap-app",
		ActorID:    actorID,
		OccurredAt: time.Now().UTC(),
		Payload:    payload,
	}
}

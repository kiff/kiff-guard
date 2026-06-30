// Package main — KIFF decide server for payment-recovery-enablement-guard.
//
// Domain: Invoice moves CREATED -> PAST_DUE -> RECOVERED.
// RETRY_PAYMENT is allowed only from PAST_DUE. The enablement story:
// a dunning agent retries the charge on a PAST_DUE invoice (allowed; the
// charge runs and the invoice advances to RECOVERED), and the same agent
// is then declined when it retries again on the now-RECOVERED invoice
// (state_not_allowed). The boundary is what lets you put the agent on
// payment recovery at all — it charges the card once to recover, it does
// not hammer it five times.
//
// Built on github.com/kiff/kiff v0.6.0.
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
	AdapterInvoice = "invoice"
	EntityInvoice  = "Invoice"

	EventInvoiceCreated   = "INVOICE_CREATED"
	EventPaymentFailed    = "PAYMENT_FAILED"
	EventPaymentRecovered = "PAYMENT_RECOVERED"

	StateCreated   = "CREATED"
	StatePastDue   = "PAST_DUE"
	StateRecovered = "RECOVERED"

	ActionRetryPayment = "RETRY_PAYMENT"

	RoleDunning = "dunning"

	PermRetry permission.Permission = "payment.retry"
)

var AgentActor = actor.Actor{
	ID:          "dunning-agent",
	Type:        actor.TypeAgent,
	DisplayName: "Dunning Agent",
	Roles:       []string{RoleDunning},
}

func NewDomainDefinition() (domain.Definition, error) {
	b := domain.New("payment-recovery-enablement").
		Entity(EntityInvoice).
		Event(EventInvoiceCreated).
		Event(EventPaymentFailed).
		Event(EventPaymentRecovered).
		Transition(EventInvoiceCreated, "", StateCreated).
		Transition(EventPaymentFailed, StateCreated, StatePastDue).
		Transition(EventPaymentRecovered, StatePastDue, StateRecovered).
		Allow(StatePastDue, ActionRetryPayment).
		Action(retryContract())
	return b.Build()
}

func retryContract() action.ActionContract {
	return action.ActionContract{
		Name:                ActionRetryPayment,
		AllowedStates:       []string{StatePastDue},
		RequiredParameters:  []string{"amount_cents", "reason"},
		RequiredPermissions: []permission.Permission{PermRetry},
		Risk:                action.RiskMedium,
		ApprovalRequirement: action.ApprovalNever,
		Executor: func(_ context.Context, ctx action.ActionContext) (action.ActionResult, error) {
			return action.ActionResult{
				ActionName:     ActionRetryPayment,
				EntityID:       ctx.EntityID,
				Status:         action.ExecutionSucceeded,
				Executed:       true,
				Message:        "charge retried; agent recovers the payment",
				EffectsSummary: "payment retried",
				ExecutedAt:     time.Now().UTC(),
			}, nil
		},
	}
}

// NewPermissionPolicy grants payment.retry to the dunning role and assigns the
// dunning agent to it. Since v0.4.0 role membership is policy-owned: the
// runtime reads AssignRole, not actor.Roles (#19), so this AssignRole call is
// what authorizes the agent — without it every RETRY_PAYMENT is denied.
func NewPermissionPolicy() *permission.SimplePolicy {
	p := permission.NewSimplePolicy()
	p.GrantRole(RoleDunning, PermRetry)
	p.AssignRole(AgentActor.ID, RoleDunning)
	return p
}

func NewInputAdapter() (adapter.Adapter, error) {
	return adapter.NewPassthroughAdapter(AdapterInvoice)
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
		Source:     "payment-app",
		ActorID:    actorID,
		OccurredAt: time.Now().UTC(),
		Payload:    payload,
	}
}

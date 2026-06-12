// Package main is the KIFF decide server for the refund-ceiling-guard
// cookbook recipe. It wraps the real KIFF runtime with a refund domain
// and exposes the decide contract the guard SDK speaks.
//
// The domain: an Order moves PAID -> PARTIALLY_REFUNDED -> FULLY_REFUNDED.
// ISSUE_REFUND is allowed only from PAID or PARTIALLY_REFUNDED, and only
// if amount_cents <= remaining_refundable. Once fully refunded, all
// further attempts are blocked (state_not_allowed).
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
	AdapterRefund = "refund"

	EntityOrder = "Order"

	EventOrderPaid          = "ORDER_PAID"
	EventRefundIssued       = "REFUND_ISSUED"
	EventOrderFullyRefunded = "ORDER_FULLY_REFUNDED"

	StatePaid              = "PAID"
	StatePartiallyRefunded = "PARTIALLY_REFUNDED"
	StateFullyRefunded     = "FULLY_REFUNDED"

	ActionIssueRefund = "ISSUE_REFUND"

	PermIssueRefund permission.Permission = "refund.issue"
)

// AgentActor is the support agent.
var AgentActor = actor.Actor{
	ID:          "support-agent",
	Type:        actor.TypeAgent,
	DisplayName: "Support Agent",
	Roles:       []string{"support"},
}

// NewDomainDefinition builds the refund domain.
func NewDomainDefinition() (domain.Definition, error) {
	b := domain.New("order-refunds").
		Entity(EntityOrder).
		Event(EventOrderPaid).
		Event(EventRefundIssued).
		Event(EventOrderFullyRefunded).
		Transition(EventOrderPaid, "", StatePaid).
		Transition(EventRefundIssued, StatePaid, StatePartiallyRefunded).
		Transition(EventRefundIssued, StatePartiallyRefunded, StatePartiallyRefunded).
		Transition(EventOrderFullyRefunded, StatePartiallyRefunded, StateFullyRefunded).
		Allow(StatePaid, ActionIssueRefund).
		Allow(StatePartiallyRefunded, ActionIssueRefund).
		Action(issueRefundContract())
	return b.Build()
}

func issueRefundContract() action.ActionContract {
	return action.ActionContract{
		Name:                ActionIssueRefund,
		AllowedStates:       []string{StatePaid, StatePartiallyRefunded},
		RequiredParameters:  []string{"amount_cents"},
		RequiredPermissions: []permission.Permission{PermIssueRefund},
		Risk:                action.RiskHigh,
		ApprovalRequirement: action.ApprovalNever,
		Executor: func(_ context.Context, ctx action.ActionContext) (action.ActionResult, error) {
			return action.ActionResult{
				ActionName:     ActionIssueRefund,
				EntityID:       ctx.EntityID,
				Status:         action.ExecutionSucceeded,
				Executed:       true,
				Message:        "refund cleared; app performs the credit",
				EffectsSummary: "refund cleared",
				ExecutedAt:     time.Now().UTC(),
			}, nil
		},
	}
}

func NewPermissionPolicy() *permission.SimplePolicy {
	p := permission.NewSimplePolicy()
	p.GrantRole("support", PermIssueRefund)
	p.GrantRole("system", PermIssueRefund)
	return p
}

func NewInputAdapter() (adapter.Adapter, error) {
	return adapter.NewPassthroughAdapter(AdapterRefund)
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

func orderEvent(orderID, eventType, actorID string, payload map[string]any) event.Event {
	return event.Event{
		ID:         fmt.Sprintf("evt-%s-%s-%d", eventType, orderID, time.Now().UnixNano()),
		Type:       eventType,
		EntityID:   orderID,
		EntityType: EntityOrder,
		Source:     "refund-app",
		ActorID:    actorID,
		OccurredAt: time.Now().UTC(),
		Payload:    payload,
	}
}

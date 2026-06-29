// Package main — KIFF decide server for refund-enablement-guard.
//
// Domain: Order moves CREATED -> PAID -> REFUNDED.
// ISSUE_REFUND is allowed only from PAID. The enablement story:
// an agent issues the refund on a PAID order (allowed; the side
// effect runs and the order advances to REFUNDED), and the same
// agent is then declined on the now-REFUNDED order (state_not_allowed)
// and on any order that was never PAID. The boundary is what lets you
// hand the agent the refund route at all.
package main

import (
	"context"
	"fmt"
	"time"

	"github.com/kiffhq/kiff/pkg/kiff/action"
	"github.com/kiffhq/kiff/pkg/kiff/actor"
	"github.com/kiffhq/kiff/pkg/kiff/adapter"
	"github.com/kiffhq/kiff/pkg/kiff/domain"
	"github.com/kiffhq/kiff/pkg/kiff/event"
	"github.com/kiffhq/kiff/pkg/kiff/permission"
	"github.com/kiffhq/kiff/pkg/kiff/runtime"
)

const (
	AdapterRefund = "refund"
	EntityOrder   = "Order"

	EventOrderCreated    = "ORDER_CREATED"
	EventPaymentCaptured = "PAYMENT_CAPTURED"
	EventRefundIssued    = "REFUND_ISSUED"

	StateCreated  = "CREATED"
	StatePaid     = "PAID"
	StateRefunded = "REFUNDED"

	ActionIssueRefund = "ISSUE_REFUND"

	PermRefund permission.Permission = "refund.issue"
)

var AgentActor = actor.Actor{
	ID:          "refund-agent",
	Type:        actor.TypeAgent,
	DisplayName: "Refund Agent",
	Roles:       []string{"refunds"},
}

func NewDomainDefinition() (domain.Definition, error) {
	b := domain.New("refund-enablement").
		Entity(EntityOrder).
		Event(EventOrderCreated).
		Event(EventPaymentCaptured).
		Event(EventRefundIssued).
		Transition(EventOrderCreated, "", StateCreated).
		Transition(EventPaymentCaptured, StateCreated, StatePaid).
		Transition(EventRefundIssued, StatePaid, StateRefunded).
		Allow(StatePaid, ActionIssueRefund).
		Action(refundContract())
	return b.Build()
}

func refundContract() action.ActionContract {
	return action.ActionContract{
		Name:                ActionIssueRefund,
		AllowedStates:       []string{StatePaid},
		RequiredParameters:  []string{"amount_cents", "reason"},
		RequiredPermissions: []permission.Permission{PermRefund},
		Risk:                action.RiskMedium,
		ApprovalRequirement: action.ApprovalNever,
		Executor: func(_ context.Context, ctx action.ActionContext) (action.ActionResult, error) {
			return action.ActionResult{
				ActionName:     ActionIssueRefund,
				EntityID:       ctx.EntityID,
				Status:         action.ExecutionSucceeded,
				Executed:       true,
				Message:        "refund cleared; agent performs the payout",
				EffectsSummary: "refund cleared",
				ExecutedAt:     time.Now().UTC(),
			}, nil
		},
	}
}

func NewPermissionPolicy() *permission.SimplePolicy {
	p := permission.NewSimplePolicy()
	p.GrantRole("refunds", PermRefund)
	p.GrantRole("system", PermRefund)
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

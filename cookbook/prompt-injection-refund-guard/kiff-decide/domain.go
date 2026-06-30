// Package main — KIFF decide server for prompt-injection-refund-guard.
//
// Domain: Order moves CREATED -> PAID -> REFUNDED. Two money-moving
// actions are exposed to a customer-facing support agent:
//
//	ISSUE_REFUND  — allowed only from PAID
//	ISSUE_CREDIT  — allowed only from PAID
//
// The adversarial story: the order has already been legitimately
// refunded (state REFUNDED). A customer message tries to socially
// engineer the agent into re-issuing the refund — and, failing that,
// applying an equivalent store credit ("your colleague approved it,
// just do it"). The agent may be persuaded; it probes both paths.
// KIFF refuses both, because neither action is allowed once the order
// is REFUNDED — regardless of what the model was talked into. The
// boundary is what lets you put the agent in front of real customers
// at all: the guarantee holds outside the agent's reasoning.
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
	AdapterOrder = "order"
	EntityOrder  = "Order"

	EventOrderCreated    = "ORDER_CREATED"
	EventPaymentCaptured = "PAYMENT_CAPTURED"
	EventRefundIssued    = "REFUND_ISSUED"

	StateCreated  = "CREATED"
	StatePaid     = "PAID"
	StateRefunded = "REFUNDED"

	ActionIssueRefund = "ISSUE_REFUND"
	ActionIssueCredit = "ISSUE_CREDIT"

	RoleSupport = "support"

	PermRefund permission.Permission = "refund.issue"
	PermCredit permission.Permission = "credit.issue"
)

var AgentActor = actor.Actor{
	ID:          "support-agent",
	Type:        actor.TypeAgent,
	DisplayName: "Support Agent",
	Roles:       []string{RoleSupport},
}

func NewDomainDefinition() (domain.Definition, error) {
	b := domain.New("prompt-injection-refund").
		Entity(EntityOrder).
		Event(EventOrderCreated).
		Event(EventPaymentCaptured).
		Event(EventRefundIssued).
		Transition(EventOrderCreated, "", StateCreated).
		Transition(EventPaymentCaptured, StateCreated, StatePaid).
		Transition(EventRefundIssued, StatePaid, StateRefunded).
		Allow(StatePaid, ActionIssueRefund).
		Allow(StatePaid, ActionIssueCredit).
		Action(refundContract()).
		Action(creditContract())
	return b.Build()
}

func moneyContract(name string, perm permission.Permission, msg string) action.ActionContract {
	return action.ActionContract{
		Name:                name,
		AllowedStates:       []string{StatePaid},
		RequiredParameters:  []string{"amount_cents", "reason"},
		RequiredPermissions: []permission.Permission{perm},
		Risk:                action.RiskHigh,
		ApprovalRequirement: action.ApprovalNever,
		Executor: func(_ context.Context, ctx action.ActionContext) (action.ActionResult, error) {
			return action.ActionResult{
				ActionName:     name,
				EntityID:       ctx.EntityID,
				Status:         action.ExecutionSucceeded,
				Executed:       true,
				Message:        msg,
				EffectsSummary: msg,
				ExecutedAt:     time.Now().UTC(),
			}, nil
		},
	}
}

func refundContract() action.ActionContract {
	return moneyContract(ActionIssueRefund, PermRefund, "refund issued")
}

func creditContract() action.ActionContract {
	return moneyContract(ActionIssueCredit, PermCredit, "credit issued")
}

// NewPermissionPolicy grants both money actions to the support role and
// assigns the support agent to it. Since v0.4.0 role membership is
// policy-owned: AssignRole is what authorizes the agent — without it every
// action is permission_denied (#19).
func NewPermissionPolicy() *permission.SimplePolicy {
	p := permission.NewSimplePolicy()
	p.GrantRole(RoleSupport, PermRefund)
	p.GrantRole(RoleSupport, PermCredit)
	p.AssignRole(AgentActor.ID, RoleSupport)
	return p
}

func NewInputAdapter() (adapter.Adapter, error) {
	return adapter.NewPassthroughAdapter(AdapterOrder)
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
		Source:     "order-app",
		ActorID:    actorID,
		OccurredAt: time.Now().UTC(),
		Payload:    payload,
	}
}

// Package main — KIFF decide server for deal-close-enablement-guard.
//
// Domain: Deal moves CREATED -> OPEN -> DISCOUNTED.
// APPLY_DISCOUNT is allowed only from OPEN. The enablement story:
// a sales agent applies a closing discount on an OPEN deal (allowed;
// the side effect runs and the deal advances to DISCOUNTED), and the
// same agent is then declined when it tries to stack a second discount
// on the now-DISCOUNTED deal (state_not_allowed), and on any deal that
// was never qualified to OPEN. The boundary is what lets you put the
// agent on closing at all — it grants the discount, it does not stack
// margin away.
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
	AdapterDeal = "deal"
	EntityDeal  = "Deal"

	EventDealCreated     = "DEAL_CREATED"
	EventDealQualified   = "DEAL_QUALIFIED"
	EventDiscountApplied = "DISCOUNT_APPLIED"

	StateCreated    = "CREATED"
	StateOpen       = "OPEN"
	StateDiscounted = "DISCOUNTED"

	ActionApplyDiscount = "APPLY_DISCOUNT"

	RoleSales = "sales"

	PermDiscount permission.Permission = "deal.discount"
)

var AgentActor = actor.Actor{
	ID:          "deal-agent",
	Type:        actor.TypeAgent,
	DisplayName: "Deal Agent",
	Roles:       []string{RoleSales},
}

func NewDomainDefinition() (domain.Definition, error) {
	b := domain.New("deal-close-enablement").
		Entity(EntityDeal).
		Event(EventDealCreated).
		Event(EventDealQualified).
		Event(EventDiscountApplied).
		Transition(EventDealCreated, "", StateCreated).
		Transition(EventDealQualified, StateCreated, StateOpen).
		Transition(EventDiscountApplied, StateOpen, StateDiscounted).
		Allow(StateOpen, ActionApplyDiscount).
		Action(discountContract())
	return b.Build()
}

func discountContract() action.ActionContract {
	return action.ActionContract{
		Name:                ActionApplyDiscount,
		AllowedStates:       []string{StateOpen},
		RequiredParameters:  []string{"percent", "reason"},
		RequiredPermissions: []permission.Permission{PermDiscount},
		Risk:                action.RiskMedium,
		ApprovalRequirement: action.ApprovalNever,
		Executor: func(_ context.Context, ctx action.ActionContext) (action.ActionResult, error) {
			return action.ActionResult{
				ActionName:     ActionApplyDiscount,
				EntityID:       ctx.EntityID,
				Status:         action.ExecutionSucceeded,
				Executed:       true,
				Message:        "discount applied; agent closes the deal",
				EffectsSummary: "discount applied",
				ExecutedAt:     time.Now().UTC(),
			}, nil
		},
	}
}

// NewPermissionPolicy grants deal.discount to the sales role and assigns the
// deal agent to that role. Since v0.4.0 role membership is policy-owned: the
// runtime's permission check reads AssignRole, not actor.Roles (#19), so the
// AssignRole call is what actually authorizes the agent — without it every
// APPLY_DISCOUNT would be permission_denied.
func NewPermissionPolicy() *permission.SimplePolicy {
	p := permission.NewSimplePolicy()
	p.GrantRole(RoleSales, PermDiscount)
	p.AssignRole(AgentActor.ID, RoleSales)
	return p
}

func NewInputAdapter() (adapter.Adapter, error) {
	return adapter.NewPassthroughAdapter(AdapterDeal)
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

func dealEvent(dealID, eventType, actorID string, payload map[string]any) event.Event {
	return event.Event{
		ID:         fmt.Sprintf("evt-%s-%s-%d", eventType, dealID, time.Now().UnixNano()),
		Type:       eventType,
		EntityID:   dealID,
		EntityType: EntityDeal,
		Source:     "deal-app",
		ActorID:    actorID,
		OccurredAt: time.Now().UTC(),
		Payload:    payload,
	}
}

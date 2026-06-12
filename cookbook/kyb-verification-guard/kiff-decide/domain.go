// Package main — KIFF decide server for kyb-verification-guard.
//
// Domain: a Business onboarding moves PENDING -> VERIFIED. RUN_KYB_CHECK
// (a paid bureau verification: Companies House / sanctions / UBO screen)
// is allowed only from PENDING. Once the business is VERIFIED, every
// re-check returns state_not_allowed — the verification runs exactly once.
//
// This is the "once-and-done" guarantee inside a structured Agno Workflow:
// a retried or re-entered workflow step must not pay the bureau twice, must
// not double-screen the same entity, and must not flip a decided KYB
// outcome. The state machine, not the workflow runner, enforces it.
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
	AdapterKYB    = "kyb"
	EntityBiz     = "Business"

	EventOnboardingStarted = "ONBOARDING_STARTED"
	EventKYBVerified       = "KYB_VERIFIED"

	StatePending  = "PENDING"
	StateVerified = "VERIFIED"

	ActionRunKYB = "RUN_KYB_CHECK"

	PermVerify permission.Permission = "kyb.verify"
)

var AgentActor = actor.Actor{
	ID:          "kyb-workflow",
	Type:        actor.TypeAgent,
	DisplayName: "KYB Verification Workflow",
	Roles:       []string{"kyb"},
}

func NewDomainDefinition() (domain.Definition, error) {
	b := domain.New("kyb-cases").
		Entity(EntityBiz).
		Event(EventOnboardingStarted).
		Event(EventKYBVerified).
		Transition(EventOnboardingStarted, "", StatePending).
		Transition(EventKYBVerified, StatePending, StateVerified).
		Allow(StatePending, ActionRunKYB).
		Action(runKYBContract())
	return b.Build()
}

func runKYBContract() action.ActionContract {
	return action.ActionContract{
		Name:                ActionRunKYB,
		AllowedStates:       []string{StatePending},
		RequiredParameters:  []string{"registration_number"},
		RequiredPermissions: []permission.Permission{PermVerify},
		Risk:                action.RiskMedium,
		ApprovalRequirement: action.ApprovalNever,
		Executor: func(_ context.Context, ctx action.ActionContext) (action.ActionResult, error) {
			return action.ActionResult{
				ActionName:     ActionRunKYB,
				EntityID:       ctx.EntityID,
				Status:         action.ExecutionSucceeded,
				Executed:       true,
				Message:        "KYB check cleared; workflow runs the bureau verification once",
				EffectsSummary: "kyb check cleared",
				ExecutedAt:     time.Now().UTC(),
			}, nil
		},
	}
}

func NewPermissionPolicy() *permission.SimplePolicy {
	p := permission.NewSimplePolicy()
	p.GrantRole("kyb", PermVerify)
	p.GrantRole("system", PermVerify)
	return p
}

func NewInputAdapter() (adapter.Adapter, error) {
	return adapter.NewPassthroughAdapter(AdapterKYB)
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

func bizEvent(bizID, eventType, actorID string, payload map[string]any) event.Event {
	return event.Event{
		ID:         fmt.Sprintf("evt-%s-%s-%d", eventType, bizID, time.Now().UnixNano()),
		Type:       eventType,
		EntityID:   bizID,
		EntityType: EntityBiz,
		Source:     "kyb-app",
		ActorID:    actorID,
		OccurredAt: time.Now().UTC(),
		Payload:    payload,
	}
}

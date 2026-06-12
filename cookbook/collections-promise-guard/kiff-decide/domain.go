// Package main — KIFF decide server for collections-promise-guard.
//
// Domain: CollectionsCase moves DELINQUENT -> PROMISE_ACTIVE -> FULFILLED | BROKEN.
// INITIATE_COLLECTIONS_CONTACT is allowed only from DELINQUENT or BROKEN.
// While PROMISE_ACTIVE, all contact attempts are blocked (state_not_allowed),
// protecting the borrower from harassment and the lender from FDCPA/CONC violation.
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
	AdapterCollections = "collections"
	EntityCase         = "CollectionsCase"

	EventCaseOpened       = "CASE_OPENED"
	EventPromiseMade      = "PROMISE_MADE"
	EventPromiseFulfilled = "PROMISE_FULFILLED"
	EventPromiseBroken    = "PROMISE_BROKEN"

	StateDelinquent    = "DELINQUENT"
	StatePromiseActive = "PROMISE_ACTIVE"
	StateFulfilled     = "FULFILLED"
	StateBroken        = "BROKEN"

	ActionContact = "INITIATE_COLLECTIONS_CONTACT"

	PermContact permission.Permission = "collections.contact"
)

var AgentActor = actor.Actor{
	ID:          "collections-agent",
	Type:        actor.TypeAgent,
	DisplayName: "Collections Agent",
	Roles:       []string{"collections"},
}

func NewDomainDefinition() (domain.Definition, error) {
	b := domain.New("collections-cases").
		Entity(EntityCase).
		Event(EventCaseOpened).
		Event(EventPromiseMade).
		Event(EventPromiseFulfilled).
		Event(EventPromiseBroken).
		Transition(EventCaseOpened, "", StateDelinquent).
		Transition(EventPromiseMade, StateDelinquent, StatePromiseActive).
		Transition(EventPromiseFulfilled, StatePromiseActive, StateFulfilled).
		Transition(EventPromiseBroken, StatePromiseActive, StateBroken).
		Allow(StateDelinquent, ActionContact).
		Allow(StateBroken, ActionContact).
		Action(contactContract())
	return b.Build()
}

func contactContract() action.ActionContract {
	return action.ActionContract{
		Name:                ActionContact,
		AllowedStates:       []string{StateDelinquent, StateBroken},
		RequiredParameters:  []string{"channel"},
		RequiredPermissions: []permission.Permission{PermContact},
		Risk:                action.RiskMedium,
		ApprovalRequirement: action.ApprovalNever,
		Executor: func(_ context.Context, ctx action.ActionContext) (action.ActionResult, error) {
			return action.ActionResult{
				ActionName:     ActionContact,
				EntityID:       ctx.EntityID,
				Status:         action.ExecutionSucceeded,
				Executed:       true,
				Message:        "contact cleared; agent performs the outreach",
				EffectsSummary: "contact cleared",
				ExecutedAt:     time.Now().UTC(),
			}, nil
		},
	}
}

func NewPermissionPolicy() *permission.SimplePolicy {
	p := permission.NewSimplePolicy()
	p.GrantRole("collections", PermContact)
	p.GrantRole("system", PermContact)
	return p
}

func NewInputAdapter() (adapter.Adapter, error) {
	return adapter.NewPassthroughAdapter(AdapterCollections)
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

func caseEvent(caseID, eventType, actorID string, payload map[string]any) event.Event {
	return event.Event{
		ID:         fmt.Sprintf("evt-%s-%s-%d", eventType, caseID, time.Now().UnixNano()),
		Type:       eventType,
		EntityID:   caseID,
		EntityType: EntityCase,
		Source:     "collections-app",
		ActorID:    actorID,
		OccurredAt: time.Now().UTC(),
		Payload:    payload,
	}
}

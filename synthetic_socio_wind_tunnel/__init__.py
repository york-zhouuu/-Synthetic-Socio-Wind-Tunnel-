"""
Synthetic Socio Wind Tunnel - CQRS Cognitive Map System

A cognitive map system following the Theater Model:
- Atlas (布景组): Read-only static map data
- Ledger (道具组): Read-write dynamic state
- Engine (引擎层): Write operations (Simulation, Collapse) + Navigation
- Perception (感知层): Read operations (Pipeline, Filters, Exploration)
- Cartography (制图服务): Offline map building

Public API exports the main services and models.

v0.4.0: Added structured error codes, events, director context, snapshots
v0.4.1: Added ExplorationService for visibility-based exploration
v0.5.0: Map enrichment (Overture Buildings + Places conflation), residential
        semantics for agent home enumeration, cartography connectivity fixes
        (OSM-shared-node intersection detection, ID dedup), project layout
        tidy (production code separated from demos, full OpenSpec scaffolding)
"""

from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.engine import (
    SimulationService,
    SimulationResult,
    CollapseService,
    DirectorContext,
    NavigationService,
)
from synthetic_socio_wind_tunnel.perception import (
    PerceptionPipeline,
    ObserverContext,
    SubjectiveView,
    ExplorationService,
)
from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    AgentRuntime,
    DailyPlan,
    EmotionalState,
    ExamineIntent,
    Intent,
    LANE_COVE_PROFILE,
    LLMClient,
    LocationPoolError,
    LocationPools,
    LockIntent,
    MoveIntent,
    OpenDoorIntent,
    PersonalityTraits,
    PickupIntent,
    PlanAction,
    PlanStep,
    Planner,
    PopulationProfile,
    Skills,
    SocialIntent,
    UnlockIntent,
    WaitIntent,
    build_location_pools,
    sample_population,
)
from synthetic_socio_wind_tunnel.memory import (
    CarryoverContext,
    DailySummary,
    EmbeddingProvider,
    MemoryEvent,
    MemoryQuery,
    MemoryRetriever,
    MemoryService,
    MemoryStore,
    NullEmbedding,
)
from synthetic_socio_wind_tunnel.orchestrator import (
    CommitRecord,
    DayRunSummary,
    EncounterCandidate,
    MultiDayAggregate,
    MultiDayResult,
    MultiDayRunner,
    Orchestrator,
    RunMode,
    SimulationSummary,
    TickContext,
    TickResult,
)
from synthetic_socio_wind_tunnel.attention import (
    AttentionService,
    AttentionState,
    DigitalProfile,
    FeedDeliveryRecord,
    FeedItem,
    NotificationEvent,
    create_notification_event,
)
from synthetic_socio_wind_tunnel.social_graph import (
    STRONG_TIE_THRESHOLD,
    SocialGraphService,
    Tie,
    WEAK_TIE_THRESHOLD,
)
from synthetic_socio_wind_tunnel.conversation import (
    ConversationService,
    Information,
    Propagation,
    ShareEvent,
)
from synthetic_socio_wind_tunnel.agent.operations import (
    ConcurrentOperationError,
    OperationPool,
    OperationResult,
    PendingOp,
)
from synthetic_socio_wind_tunnel.fitness import (
    AuditResult,
    AuditStatus,
    CategoryResult,
    FitnessReport,
    run_audit,
)
from synthetic_socio_wind_tunnel.map_service import (
    MapService,
    KnownDestination,
    CurrentScene,
    LocationDetail,
)
from synthetic_socio_wind_tunnel.policy_hack import (
    PUSH_TEMPLATES,
    PushPersonalizer,
    PushTemplate,
    VARIANTS,
    CatalystSeedingVariant,
    GlobalDistractionVariant,
    HyperlocalPushVariant,
    PhaseController,
    PhoneFrictionVariant,
    SharedAnchorVariant,
    Variant,
    VariantContext,
    VariantRunnerAdapter,
)
from synthetic_socio_wind_tunnel.metrics import (
    ContestReport,
    ContestRow,
    DayMetricsSummary,
    EvidenceAlignment,
    RunMetrics,
    SuiteAggregate,
    TickMetricsRecorder,
    build_contest_report,
    build_run_metrics,
    build_suite_aggregate,
    write_markdown,
)
from synthetic_socio_wind_tunnel.core.errors import SimulationErrorCode, EventType
from synthetic_socio_wind_tunnel.core.events import WorldEvent
from synthetic_socio_wind_tunnel.perception.models import (
    EntitySnapshot,
    ItemSnapshot,
    ContainerSnapshot,
    ClueSnapshot,
)
from synthetic_socio_wind_tunnel.run_resilience import (
    AllKeysOpenError,
    DayCheckpointWriter,
    HealthAudit,
    HealthAuditReport,
    HotfixSignalHandler,
    IncompatibleCheckpointError,
    PerKeyCircuitBreaker,
    RetryPolicy,
    SimulationCheckpoint,
    SnapshotPolicy,
    WorkerSnapshot,
)
from synthetic_socio_wind_tunnel.data_loader import (
    SimulationContentCache,
    is_cache_complete,
    load_setup_cache,
    save_setup_cache,
)

__version__ = "0.9.0"
__all__ = [
    # Data Layer
    "Atlas",
    "Ledger",
    # Engine Layer (Write + Navigation)
    "SimulationService",
    "SimulationResult",
    "CollapseService",
    "DirectorContext",
    "NavigationService",
    # Perception Layer (Read)
    "PerceptionPipeline",
    "ObserverContext",
    "SubjectiveView",
    "ExplorationService",
    # Agent Layer (Phase 1)
    "AgentProfile",
    "AgentRuntime",
    "Planner",
    "DailyPlan",
    "PlanStep",
    "LLMClient",
    # Agent Population (realign-to-social-thesis)
    "PopulationProfile",
    "LANE_COVE_PROFILE",
    "sample_population",
    # Typed location pools (fix-population-uses-typed-locations)
    "LocationPools",
    "LocationPoolError",
    "build_location_pools",
    # Attention Channel (realign-to-social-thesis)
    "AttentionService",
    "AttentionState",
    "DigitalProfile",
    "FeedItem",
    "FeedDeliveryRecord",
    "NotificationEvent",
    "create_notification_event",
    # Social Graph (social-graph-capability)
    "SocialGraphService",
    "Tie",
    "WEAK_TIE_THRESHOLD",
    "STRONG_TIE_THRESHOLD",
    # Conversation (conversation-capability)
    "ConversationService",
    "Information",
    "Propagation",
    "ShareEvent",
    # Fitness Audit (realign-to-social-thesis)
    "run_audit",
    "FitnessReport",
    "AuditResult",
    "AuditStatus",
    "CategoryResult",
    # Orchestrator (phase 2)
    "Orchestrator",
    "TickContext",
    "TickResult",
    "CommitRecord",
    "EncounterCandidate",
    "SimulationSummary",
    # Multi-day runner (multi-day-simulation)
    "MultiDayRunner",
    "MultiDayResult",
    "MultiDayAggregate",
    "DayRunSummary",
    "RunMode",
    # Intents (phase 2 — used with orchestrator)
    "Intent",
    "MoveIntent",
    "WaitIntent",
    "ExamineIntent",
    "PickupIntent",
    "OpenDoorIntent",
    "UnlockIntent",
    "LockIntent",
    # Typed personality (typed-personality)
    "PersonalityTraits",
    "Skills",
    "EmotionalState",
    "PlanAction",
    "SocialIntent",
    # Memory (memory)
    "MemoryService",
    "MemoryEvent",
    "MemoryQuery",
    "MemoryStore",
    "MemoryRetriever",
    "DailySummary",
    "EmbeddingProvider",
    "NullEmbedding",
    # Memory carryover (multi-day-simulation)
    "CarryoverContext",
    # Policy Hack (policy-hack)
    "Variant",
    "VariantContext",
    "VariantRunnerAdapter",
    "PhaseController",
    "HyperlocalPushVariant",
    "GlobalDistractionVariant",
    "PhoneFrictionVariant",
    "SharedAnchorVariant",
    "CatalystSeedingVariant",
    "VARIANTS",
    "PushPersonalizer",
    "PushTemplate",
    "PUSH_TEMPLATES",
    # Agent operations (agent-stack-aitown-port)
    "ConcurrentOperationError",
    "OperationPool",
    "OperationResult",
    "PendingOp",
    # Metrics (metrics)
    "TickMetricsRecorder",
    "DayMetricsSummary",
    "RunMetrics",
    "SuiteAggregate",
    "ContestReport",
    "ContestRow",
    "EvidenceAlignment",
    "build_run_metrics",
    "build_suite_aggregate",
    "build_contest_report",
    "write_markdown",
    # Map Service (agent-facing query façade)
    "MapService",
    "KnownDestination",
    "CurrentScene",
    "LocationDetail",
    # Snapshot Models
    "EntitySnapshot",
    "ItemSnapshot",
    "ContainerSnapshot",
    "ClueSnapshot",
    # Error & Event System
    "SimulationErrorCode",
    "EventType",
    "WorldEvent",
    # Run Resilience (run-resilience, D1' 2026-05-15 fix)
    "AllKeysOpenError",
    "DayCheckpointWriter",
    "HealthAudit",
    "HealthAuditReport",
    "HotfixSignalHandler",
    "IncompatibleCheckpointError",
    "PerKeyCircuitBreaker",
    "RetryPolicy",
    "WorkerSnapshot",
    # Tick-Level Resume (tick-level-resume, 2026-05-16)
    "SimulationCheckpoint",
    "SnapshotPolicy",
    # Setup Content Cache (setup-content-cache, 2026-05-16)
    "SimulationContentCache",
    "load_setup_cache",
    "save_setup_cache",
    "is_cache_complete",
]

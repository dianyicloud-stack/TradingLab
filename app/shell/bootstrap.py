"""Sole composition root: wire domain-owned capabilities, never business rules."""
from dataclasses import dataclass
from pathlib import Path
from adapters.baselines import verify_baselines
from app.account.module import create_module as account_module
from app.account.portfolio import PortfolioService
from app.account.portfolio_router import PortfolioRouter
from engines.account.engine import AccountEngine
from engines.account.ledger import AccountRepository
from engines.account.quotes import QuoteService
from adapters.market_quote import SinaQuoteProvider
from app.live.module import create_module as live_module
from app.shell.registry import ModuleRegistry
from app.system.module import create_module as system_module
from app.system.service import SystemHealth
from app.system.module import HealthRouter
from contracts.system import HealthCheck
from shared.config import ScopedStore, Settings
from bridges.config import LiveConfig
from engines.live.loop import LiveLoop
from engines.live.advisory_repository import AdvisoryRuntimeRepository,AdvisoryOpinionRepository
from engines.live.advisory import AdvisoryService
from app.live.router import LiveRouter
from app.live.observation import ObservationRouter,create_module as observation_module
from bridges.market_agent import AgentClient,AgentFactBridge
from adapters.source_configuration import source_configuration
from adapters.market_source_lifecycle import SourceLifecycle
from bridges.active_market_source import ActiveMarketSource
from app.system.market_source import MarketSourceService
from app.system.source_router import SourceRouter

from adapters.ai.advisory import AdvisoryProvider

DATA_DIRECTORIES=('runtime/live','live/advisory','account/unified','system')

@dataclass(frozen=True)
class Application:
    registry: ModuleRegistry
    system_health: SystemHealth
    routers: tuple=()
    live_loop: LiveLoop|None=None
    portfolio: PortfolioService|None=None
    market_source: object=None
    command_guard: object=None
    runtime: object=None


def build_application(settings: Settings,*,live_bridge=None,advisory_provider=None,quote_provider=None,agent_client=None,
                      market_source_overrides=None,source_lifecycle=None):
    data=ScopedStore(settings.data_root,boundary=settings.project_root);data.ensure()
    for directory in DATA_DIRECTORIES:data.child(directory).ensure()
    live_config = LiveConfig.load(settings.project_root) if settings.source == 'USER' else LiveConfig()
    source_repo, source_config = source_configuration(settings.project_root, settings.data_root, settings.source, market_source_overrides)
    managed_source = live_bridge is None or market_source_overrides is not None
    agent_client=agent_client or AgentClient(source_config['market_agent_root'],source=settings.source)
    source_provider=None
    if managed_source:
        source_provider=ActiveMarketSource(AgentFactBridge(agent_client),source_config)
        live_bridge=source_provider
    elif settings.source!='TEST':
        raise ValueError('PRODUCTION_SOURCE_MUST_BE_MARKET_AGENT')
    live_loop=LiveLoop(live_bridge,source=settings.source,interval=live_config.interval_seconds)
    configured_advisory_provider=advisory_provider or AdvisoryProvider(settings.project_root)
    live_loop.advisory=AdvisoryService(live_loop.workspace,AdvisoryRuntimeRepository(data.child('runtime/live/advisory')),
                                      AdvisoryOpinionRepository(data.child('live/advisory')),
                                      configured_advisory_provider,source=settings.source)
    from app.system.ai_configuration import AIConfiguration,AIConfigurationRouter
    ai_configuration=None
    if advisory_provider is None:
        ai_configuration=AIConfiguration(data.child('system'),configured_advisory_provider,live_loop.advisory.catalog()['global'])
        live_loop.advisory.model_configuration=ai_configuration
    live_quote_provider=quote_provider or (SinaQuoteProvider() if settings.source=='USER' else None)
    live_loop.advisory.stock_metadata=live_quote_provider or (lambda symbol:None)
    live_loop.advisory.listener_state=lambda:live_loop.status
    portfolio=PortfolioService(AccountEngine(AccountRepository(data.child('account/unified'))),
        QuoteService(live_loop.workspace,fallback=live_quote_provider),namespace=settings.source)
    live_loop.advisory.portfolio_context=lambda symbol:portfolio.context(symbol,refresh=False)
    live_loop.advisory.market_is_open=portfolio.engine.rules.calendar.is_open
    live_loop.advisory.portfolio_result=portfolio.on_advisory
    portfolio.advisory_reader=live_loop.advisory.execution_bundle
    source_service=None
    if source_provider:
        def source_quiescent():
            if live_loop.status != 'STOPPED' or live_loop.thread and live_loop.thread.is_alive():return False
            return not live_loop.advisory.runtime.has_running_work()
        lifecycle=source_lifecycle or SourceLifecycle(settings.project_root,source_config)
        source_service=MarketSourceService(source_repo,source_config,source_provider,lifecycle,source_quiescent)

    from app.live.tracking_delete import LiveTrackingDeletion
    tracking_deletion=LiveTrackingDeletion(agent_client,live_loop.advisory,portfolio.tracking_references)
    def baseline_health():
        report = verify_baselines(settings.project_root)
        versions = " · ".join(f"{item['version']}={item['status']}" for item in report["authoritative_checks"])
        detail = f"{report['file_count']} files · {report['frozen_baselines']}"
        if versions:
            detail += f" · {versions}"
        return HealthCheck("frozen_baselines", "Frozen Baselines", report["status"], detail)

    health=SystemHealth((
        ('frozen_baselines',baseline_health),
        ('configuration',lambda:HealthCheck('configuration','Configuration','READY','本地服务 · 所有者数据隔离')),
        ('account_stores',portfolio.health),
        *((item.id,lambda identity=item.id:next(row for row in live_loop.health_checks() if row.id==identity)) for item in live_loop.health_checks()),
    ),cache_path=data.child('runtime/system').path('last-health.json'))
    from app.system.maintenance import MaintenanceService,MaintenanceRouter
    from adapters.history_bars import SinaDailyBars
    from engines.history.store import HistoryStore
    from engines.history.bars import BarsEngine
    from engines.history.service import HistoricalAnalysis
    from app.live.history import HistoryRouter
    history_store=HistoryStore(data.child('live/history').path())
    history_bars=BarsEngine(history_store,SinaDailyBars(),portfolio.engine.rules.calendar)
    history_analysis=HistoricalAnalysis(history_bars,history_store,configured_advisory_provider,
        lambda:live_loop.advisory.catalog()['global'],settings.source,
        name_resolver=lambda symbol:(live_loop.advisory.stock_metadata(symbol) or {}).get('instrument_name'))
    history_analysis.model_configuration=ai_configuration
    maintenance=MaintenanceService(data.child('system'),live_loop.advisory,agent_client,portfolio,lambda:[],portfolio.engine.rules.calendar,
        inventory_root=settings.project_root if settings.source=='USER' else data.path(),
        artifact_root=settings.project_root/'artifacts' if settings.source=='USER' else data.child('test_artifacts').path(),protected_roots=(data.path(),))
    from adapters.telegram import load_config,TelegramSender
    from app.system.notifications import Notifications,NotificationRouter
    notification_config=load_config(settings.project_root,settings.source)
    notifications=Notifications(data.child('system/notifications'),notification_config,TelegramSender(notification_config),live_loop.advisory,settings.source)
    live_loop.advisory.success_observer=notifications.completed
    from app.system.runtime_web import WebRuntime,RuntimeRouter
    runtime=WebRuntime(settings.data_root,live_loop,history_analysis,notifications)
    registry=ModuleRegistry((live_module(live_loop.health),observation_module(agent_client),account_module(portfolio.health),system_module(health)))
    routers=(RuntimeRouter(runtime,settings.data_root),PortfolioRouter(portfolio),LiveRouter(live_loop),ObservationRouter(agent_client,live_loop.advisory.latest,source_provider,tracking_deletion),
             HealthRouter(health),*((AIConfigurationRouter(ai_configuration),) if ai_configuration else ()),MaintenanceRouter(maintenance),NotificationRouter(notifications),HistoryRouter(history_bars,history_analysis,history_store),
             *((SourceRouter(source_service),) if source_service else ()))
    return Application(registry,health,routers,live_loop,portfolio,source_service,source_service.command_guard if source_service else None,runtime)

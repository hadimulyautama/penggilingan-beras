"""Facade model: re-export semua model + Base agar Alembic & aplikasi menemukannya.

Definisi model tinggal di paket domain (app.penggilingan.gudang1.models, app.penggilingan.gudang2.models)
dan master/system/transfer di sini. Konsumen tetap pakai `from app.models import X`.
"""
from app.database import Base
from app.models.master import (
    Dryer,
    Pelanggan,
    Silo,
    Supplier,
    User,
    Warehouse,
)
from app.penggilingan.gudang1.models import (
    DryingCoolingLog,
    DryingLot,
    DryingLotBatch,
    DryingMoistureLog,
    MillingPkRouting,
    MillingProcess,
    MillingProcessVerification,
    MillingProgressLog,
    MillingQcLog,
    PkStockGudang1,
    PurchaseBatch,
    PurchaseBatchVerification,
    SiloMovingLog,
    SiloStorage,
)
from app.penggilingan.gudang2.models import (
    PkGudang2Intake,
    PkPurchaseBatch,
    PkPurchaseVerification,
    PkRejection,
    PkTumpukanToSilo,
    PolishingOutputLog,
    PolishingProcess,
    PolishingSiloUsage,
)
from app.penggilingan.inventory.models import (
    Brand,
    ByproductPrice,
    ByproductStock,
    FinishedGoodsStock,
    OutgoingItem,
    OutgoingRecord,
    PackageSize,
    PackagingLoss,
    PackagingMaterial,
    PackagingPurchase,
    ProductSku,
    RiceQualityStandard,
)
from app.models.system import ActivityLog, Notification
from app.models.transfer import InternalTransfer

__all__ = [
    "Base",
    # master
    "Warehouse",
    "User",
    "Pelanggan",
    "Supplier",
    "Silo",
    "Dryer",
    # gudang1
    "PurchaseBatch",
    "PurchaseBatchVerification",
    "DryingLot",
    "DryingLotBatch",
    "DryingMoistureLog",
    "DryingCoolingLog",
    "SiloMovingLog",
    "SiloStorage",
    "MillingProcess",
    "MillingProgressLog",
    "MillingPkRouting",
    "MillingQcLog",
    "MillingProcessVerification",
    "PkStockGudang1",
    # gudang2
    "PkPurchaseBatch",
    "PkPurchaseVerification",
    "PkRejection",
    "PkGudang2Intake",
    "PkTumpukanToSilo",
    "PolishingProcess",
    "PolishingSiloUsage",
    "PolishingOutputLog",
    # inventory (produk & kemasan)
    "RiceQualityStandard",
    "Brand",
    "PackagingMaterial",
    "PackageSize",
    "ProductSku",
    "PackagingPurchase",
    "PackagingLoss",
    "FinishedGoodsStock",
    "ByproductStock",
    "ByproductPrice",
    "OutgoingRecord",
    "OutgoingItem",
    # transfer (bridge)
    "InternalTransfer",
    # system
    "ActivityLog",
    "Notification",
]

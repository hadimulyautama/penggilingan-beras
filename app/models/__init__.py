"""Facade model: re-export semua model + Base agar Alembic & aplikasi menemukannya.

Definisi model tinggal di paket domain (app.penggilingan.gudang1.models, app.penggilingan.gudang2.models)
dan master/system/transfer di sini. Konsumen tetap pakai `from app.models import X`.
"""
from app.database import Base
from app.models.master import (
    Armada,
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
    GabahKeringBongkar,
    GabahKeringLot,
    JedaProses,
    MillingProcess,
    MillingProcessSource,
    MillingProcessVerification,
    MillingProgressLog,
    MillingQcLog,
    PurchaseBatch,
    PurchaseBatchQc,
    PurchaseBatchQcSample,
    PurchaseBatchVerification,
    SiloMovingLog,
    SiloStorage,
)
from app.penggilingan.gudang2.models import (
    BerasKeSilo,
    BrokenKeSilo,
    HasilSampingKeSilo,
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
    KemasanTara,
    ReturRincian,
    CustomerReturn,
    CustomerReturnItem,
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
from app.models.akun import ProduksiAkun
from app.models.jasa import Jasa
from app.models.peristiwa import (Peristiwa, ProyeksiGabahMasuk, ProyeksiPindahTumpukanSilo,
                                  ProyeksiPkLuarMasuk, ProyeksiPkMasukG2, ProyeksiTransferPk)
from app.models.system import ActivityLog, KodeUrut, Notification, SetelanPabrik
from app.models.permintaan import PermintaanPk
from app.models.transfer import InternalTransfer
from app.models import cermin  # noqa: E402,F401  (pasang saringan cermin bertanda)

__all__ = [
    "Base",
    # master
    "Warehouse",
    "User",
    "Pelanggan",
    "Supplier",
    "Silo",
    "Dryer",
    "Armada",
    # gudang1
    "PurchaseBatch",
    "PurchaseBatchVerification",
    "PurchaseBatchQc",
    "PurchaseBatchQcSample",
    "DryingLot",
    "DryingLotBatch",
    "DryingMoistureLog",
    "JedaProses",
    "DryingCoolingLog",
    "SiloMovingLog",
    "SiloStorage",
    "GabahKeringLot",
    "GabahKeringBongkar",
    "MillingProcess",
    "MillingProgressLog",
    "MillingQcLog",
    "MillingProcessVerification",
        # gudang2
    "PkPurchaseBatch",
    "PkPurchaseVerification",
    "PkRejection",
    "PkGudang2Intake",
    "PkTumpukanToSilo",
    "BrokenKeSilo",
    "BerasKeSilo",
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
    "KemasanTara",
    "ReturRincian",
    "CustomerReturn",
    "CustomerReturnItem",
    "ByproductStock",
    "ByproductPrice",
    "OutgoingRecord",
    "OutgoingItem",
    # jasa (toll milling) — pemilik barang, bukan pembelinya
    "Jasa",
    # transfer (bridge)
    "InternalTransfer",
    "PermintaanPk",
    # system
    "ActivityLog",
    "KodeUrut",
    "SetelanPabrik",
    "Notification",
    # akun webapp (kredensial; peran tetap di users)
    "ProduksiAkun",
    "Peristiwa",
    "ProyeksiGabahMasuk",
    "ProyeksiPkLuarMasuk",
    "ProyeksiPkMasukG2",
    "ProyeksiTransferPk",
    "ProyeksiPindahTumpukanSilo",
]

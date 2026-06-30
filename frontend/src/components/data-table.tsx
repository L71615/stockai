"use client"

// Barrel file — re-exports from split modules for backward compatibility.
// Components originally in this file have been split into:
//   data-table-core.tsx   — DataTable + buildColumns + DraggableRow + Pagination
//   data-table-cells.tsx  — Cell renderers (DragHandle, PnlCell, ActionsCell, etc.)
//   data-table-drawer.tsx — StockDetailDrawer (K-line mini chart drawer)

export { DataTable, schema, type HoldingRow } from "./data-table-core"
export { StockDetailDrawer, stockDetailSchema, type StockDetailItem } from "./data-table-drawer"
export type { HoldingRowActionMap } from "./data-table-cells"

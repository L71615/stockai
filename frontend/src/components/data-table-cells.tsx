"use client"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  IconGripVertical,
  IconTrendingUp,
  IconTrendingDown,
  IconDotsVertical,
} from "@tabler/icons-react"
import { useSortable } from "@dnd-kit/sortable"
import { StockDetailDrawer, type StockDetailItem } from "./data-table-drawer"
import {
  createHoldingRowActionHandlers,
  getHoldingRowActionLabels,
  type HoldingRowActionCallbacks,
} from "@/lib/holding-row-actions"

export type HoldingRowActionMap = Partial<HoldingRowActionCallbacks<StockDetailItem>>

// ── DragHandle ──

export function DragHandle({ id }: { id: number }) {
  const { attributes, listeners } = useSortable({ id })
  return (
    <Button
      {...attributes}
      {...listeners}
      variant="ghost"
      size="icon"
      className="size-7 text-muted-foreground hover:bg-transparent"
    >
      <IconGripVertical className="size-3 text-muted-foreground" />
      <span className="sr-only">拖动排序</span>
    </Button>
  )
}

// ── Cell renderers ──

export function SelectHeaderCell({ table }: { table: any }) {
  return (
    <div className="flex items-center justify-center">
      <Checkbox
        checked={
          table.getIsAllPageRowsSelected() ||
          (table.getIsSomePageRowsSelected() && "indeterminate")
        }
        onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
        aria-label="全选"
      />
    </div>
  )
}

export function SelectCell({ row }: { row: any }) {
  return (
    <div className="flex items-center justify-center">
      <Checkbox
        checked={row.getIsSelected()}
        onCheckedChange={(value) => row.toggleSelected(!!value)}
        aria-label="选择行"
      />
    </div>
  )
}

export function CodeCell({ item }: { item: StockDetailItem }) {
  return <span className="font-mono text-xs">{item.code}</span>
}

export function NameCell({ item }: { item: StockDetailItem }) {
  return <StockDetailDrawer item={item} />
}

export function SharesCell({ item }: { item: StockDetailItem }) {
  return <div className="text-right font-mono tabular-nums">{item.shares}</div>
}

export function PriceCell({ item }: { item: StockDetailItem }) {
  return <div className="text-right font-mono tabular-nums">{item.price}</div>
}

export function CostCell({ item }: { item: StockDetailItem }) {
  return (
    <div className="text-right font-mono tabular-nums text-muted-foreground">
      {item.cost}
    </div>
  )
}

export function PnlCell({ item }: { item: StockDetailItem }) {
  const isUp = item.pnl.startsWith("+")
  return (
    <div
      className={cn(
        "text-right font-mono tabular-nums font-medium",
        isUp ? "text-red-500" : "text-emerald-500"
      )}
    >
      {item.pnl}
    </div>
  )
}

export function PnlPctCell({ item }: { item: StockDetailItem }) {
  const isUp = item.pnlPct.startsWith("+")
  return (
    <Badge
      variant="outline"
      className={cn(
        "font-mono tabular-nums",
        isUp
          ? "text-red-500 border-red-500/20 bg-red-500/5"
          : "text-emerald-500 border-emerald-500/20 bg-emerald-500/5"
      )}
    >
      {isUp ? <IconTrendingUp className="size-3" /> : <IconTrendingDown className="size-3" />}
      {item.pnlPct}
    </Badge>
  )
}

export function ActionsCell({
  item,
  activeActions,
}: {
  item: StockDetailItem
  activeActions?: HoldingRowActionMap
}) {
  const labels = getHoldingRowActionLabels()
  const handlers = createHoldingRowActionHandlers(item, {
    onEdit: activeActions?.onEdit ?? (() => {}),
    onView: activeActions?.onView ?? (() => {}),
    onAddToWatchlist: activeActions?.onAddToWatchlist ?? (() => {}),
    onDelete: activeActions?.onDelete ?? (() => {}),
  })

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className="flex size-8 text-muted-foreground data-[state=open]:bg-muted"
          size="icon"
        >
          <IconDotsVertical />
          <span className="sr-only">操作</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-32">
        <DropdownMenuItem onClick={handlers.edit}>{labels[0]}</DropdownMenuItem>
        <DropdownMenuItem onClick={handlers.view}>{labels[1]}</DropdownMenuItem>
        <DropdownMenuItem onClick={handlers.addToWatchlist}>{labels[2]}</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onClick={handlers.delete}>{labels[3]}</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

"use client"

import * as React from "react"
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type UniqueIdentifier,
} from "@dnd-kit/core"
import { restrictToVerticalAxis } from "@dnd-kit/modifiers"
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import {
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type ColumnFiltersState,
  type Row,
  type SortingState,
  type VisibilityState,
  type Table as TanstackTable,
} from "@tanstack/react-table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import {
  IconLayoutColumns,
  IconChevronDown,
  IconChevronsLeft,
  IconChevronLeft,
  IconChevronRight,
  IconChevronsRight,
} from "@tabler/icons-react"

import {
  DragHandle,
  SelectHeaderCell,
  SelectCell,
  CodeCell,
  NameCell,
  SharesCell,
  PriceCell,
  CostCell,
  PnlCell,
  PnlPctCell,
  ActionsCell,
  type HoldingRowActionMap,
} from "./data-table-cells"
import { stockDetailSchema, type StockDetailItem } from "./data-table-drawer"

// Re-export schema for barrel
export { stockDetailSchema as schema }
export type HoldingRow = StockDetailItem

// ── buildColumns ──

function buildColumns(activeActions?: HoldingRowActionMap): ColumnDef<HoldingRow>[] {
  return [
    {
      id: "drag",
      header: () => null,
      cell: ({ row }) => <DragHandle id={row.original.id} />,
    },
    {
      id: "select",
      header: ({ table }) => <SelectHeaderCell table={table} />,
      cell: ({ row }) => <SelectCell row={row} />,
      enableSorting: false,
      enableHiding: false,
    },
    {
      accessorKey: "code",
      header: "代码",
      cell: ({ row }) => <CodeCell item={row.original} />,
      enableHiding: false,
    },
    {
      accessorKey: "name",
      header: "名称",
      cell: ({ row }) => <NameCell item={row.original} />,
      enableHiding: false,
    },
    {
      accessorKey: "shares",
      header: () => <div className="w-full text-right">持仓(股)</div>,
      cell: ({ row }) => <SharesCell item={row.original} />,
    },
    {
      accessorKey: "price",
      header: () => <div className="w-full text-right">现价</div>,
      cell: ({ row }) => <PriceCell item={row.original} />,
    },
    {
      accessorKey: "cost",
      header: () => <div className="w-full text-right">成本</div>,
      cell: ({ row }) => <CostCell item={row.original} />,
    },
    {
      accessorKey: "pnl",
      header: () => <div className="w-full text-right">盈亏</div>,
      cell: ({ row }) => <PnlCell item={row.original} />,
    },
    {
      accessorKey: "pnlPct",
      header: () => <div className="w-full text-right">盈亏%</div>,
      cell: ({ row }) => <PnlPctCell item={row.original} />,
    },
    {
      id: "actions",
      cell: ({ row }) => <ActionsCell item={row.original} activeActions={activeActions} />,
    },
  ]
}

// ── DraggableRow ──

function DraggableRow({ row }: { row: Row<HoldingRow> }) {
  const { transform, transition, setNodeRef, isDragging } = useSortable({
    id: row.original.id,
  })

  return (
    <TableRow
      data-state={row.getIsSelected() && "selected"}
      data-dragging={isDragging}
      ref={setNodeRef}
      className="relative z-0 data-[dragging=true]:z-10 data-[dragging=true]:opacity-80"
      style={{
        transform: CSS.Transform.toString(transform),
        transition: transition,
      }}
    >
      {row.getVisibleCells().map((cell) => (
        <TableCell key={cell.id}>
          {flexRender(cell.column.columnDef.cell, cell.getContext())}
        </TableCell>
      ))}
    </TableRow>
  )
}

// ── DataTable ──

export function DataTable({
  data: initialData,
  actions,
}: {
  data: HoldingRow[]
  actions?: HoldingRowActionMap
}) {
  const [data, setData] = React.useState(() => initialData)

  // 同步外部数据变化（持仓刷新后自动更新表格）
  React.useEffect(() => {
    setData(initialData)
  }, [initialData])
  const [rowSelection, setRowSelection] = React.useState({})
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({})
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([])
  const [sorting, setSorting] = React.useState<SortingState>([])
  const [pagination, setPagination] = React.useState({
    pageIndex: 0,
    pageSize: 10,
  })
  const sortableId = React.useId()
  const sensors = useSensors(
    useSensor(MouseSensor, {}),
    useSensor(TouchSensor, {}),
    useSensor(KeyboardSensor, {})
  )

  const dataIds = React.useMemo<UniqueIdentifier[]>(
    () => data?.map(({ id }) => id) || [],
    [data]
  )

  const columns = React.useMemo(() => buildColumns(actions), [actions])

  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      columnVisibility,
      rowSelection,
      columnFilters,
      pagination,
    },
    getRowId: (row) => row.id.toString(),
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
  })

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (active && over && active.id !== over.id) {
      setData((data) => {
        const oldIndex = dataIds.indexOf(active.id)
        const newIndex = dataIds.indexOf(over.id)
        return arrayMove(data, oldIndex, newIndex)
      })
    }
  }

  // Filter helpers
  const profitCount = data.filter((d) => d.pnl.startsWith("+")).length
  const lossCount = data.filter((d) => d.pnl.includes("-")).length

  const renderTable = (filterPred: (d: HoldingRow) => boolean, emptyText: string, dndId: string) => {
    const filtered = table.getRowModel().rows.filter((row) => filterPred(row.original))
    if (!filtered.length) {
      return (
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-muted">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} colSpan={header.colSpan}>
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell colSpan={columns.length} className="h-24 text-center">
                {emptyText}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      )
    }

    return (
      <DndContext
        collisionDetection={closestCenter}
        modifiers={[restrictToVerticalAxis]}
        onDragEnd={handleDragEnd}
        sensors={sensors}
        id={dndId}
      >
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-muted">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} colSpan={header.colSpan}>
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody className="**:data-[slot=table-cell]:first:w-8">
            <SortableContext
              items={dataIds}
              strategy={verticalListSortingStrategy}
            >
              {filtered.map((row) => (
                <DraggableRow key={row.id} row={row} />
              ))}
            </SortableContext>
          </TableBody>
        </Table>
      </DndContext>
    )
  }

  const [activeTab, setActiveTab] = React.useState("holdings")

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full flex-col justify-start gap-6">
      <div className="flex items-center justify-between px-4 lg:px-6">
        <Label htmlFor="view-selector" className="sr-only">视图</Label>
        <Select value={activeTab} onValueChange={setActiveTab}>
          <SelectTrigger className="flex w-fit @4xl/main:hidden" size="sm" id="view-selector">
            <SelectValue placeholder="选择视图" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="holdings">全部持仓</SelectItem>
            <SelectItem value="profit">盈利持仓</SelectItem>
            <SelectItem value="loss">亏损持仓</SelectItem>
          </SelectContent>
        </Select>
        <TabsList className="hidden @4xl/main:flex">
          <TabsTrigger value="holdings">全部持仓</TabsTrigger>
          <TabsTrigger value="profit">
            盈利 <Badge variant="secondary" className="text-red-500">{profitCount}</Badge>
          </TabsTrigger>
          <TabsTrigger value="loss">
            亏损 <Badge variant="secondary" className="text-emerald-500">{lossCount}</Badge>
          </TabsTrigger>
        </TabsList>

        <div className="flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <IconLayoutColumns data-icon="inline-start" />
                列表
                <IconChevronDown data-icon="inline-end" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-32">
              {table
                .getAllColumns()
                .filter(
                  (column) =>
                    typeof column.accessorFn !== "undefined" && column.getCanHide()
                )
                .map((column) => {
                  return (
                    <DropdownMenuCheckboxItem
                      key={column.id}
                      className="capitalize"
                      checked={column.getIsVisible()}
                      onCheckedChange={(value) => column.toggleVisibility(!!value)}
                    >
                      {column.id}
                    </DropdownMenuCheckboxItem>
                  )
                })}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* 只渲染当前 Tab，避免 3 套 DndContext + DraggableRow 同时挂载 */}
      <TabsContent value="holdings" className="relative flex flex-col gap-4 overflow-auto px-4 lg:px-6">
        {activeTab === "holdings" && (
          <>
            <div className="overflow-hidden rounded-none border">
              {renderTable(() => true, "暂无数据", sortableId)}
            </div>
            <Pagination table={table} />
          </>
        )}
      </TabsContent>

      <TabsContent value="profit" className="relative flex flex-col gap-4 overflow-auto px-4 lg:px-6">
        {activeTab === "profit" && (
          <div className="overflow-hidden rounded-none border">
            {renderTable((d) => d.pnl.startsWith("+"), "暂无盈利持仓", `${sortableId}-profit`)}
          </div>
        )}
      </TabsContent>

      <TabsContent value="loss" className="relative flex flex-col gap-4 overflow-auto px-4 lg:px-6">
        {activeTab === "loss" && (
          <div className="overflow-hidden rounded-none border">
            {renderTable((d) => d.pnl.includes("-"), "暂无亏损持仓", `${sortableId}-loss`)}
          </div>
        )}
      </TabsContent>
    </Tabs>
  )
}

// ── Pagination (extracted from DataTable) ──

function Pagination({ table }: { table: TanstackTable<HoldingRow> }) {
  return (
    <div className="flex items-center justify-between px-4">
      <div className="hidden flex-1 text-sm text-muted-foreground lg:flex">
        共 {table.getFilteredSelectedRowModel().rows.length} /{" "}
        {table.getFilteredRowModel().rows.length} 条
      </div>
      <div className="flex w-full items-center gap-8 lg:w-fit">
        <div className="hidden items-center gap-2 lg:flex">
          <Label htmlFor="rows-per-page" className="text-sm font-medium">
            每页
          </Label>
          <Select
            value={`${table.getState().pagination.pageSize}`}
            onValueChange={(value) => {
              table.setPageSize(Number(value))
            }}
          >
            <SelectTrigger size="sm" className="w-20" id="rows-per-page">
              <SelectValue placeholder={table.getState().pagination.pageSize} />
            </SelectTrigger>
            <SelectContent side="top">
              {[10, 20, 30, 40, 50].map((pageSize) => (
                <SelectItem key={pageSize} value={`${pageSize}`}>
                  {pageSize}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex w-fit items-center justify-center text-sm font-medium">
          第 {table.getState().pagination.pageIndex + 1} / {table.getPageCount()} 页
        </div>
        <div className="ml-auto flex items-center gap-2 lg:ml-0">
          <Button
            variant="outline"
            className="hidden h-8 w-8 p-0 lg:flex"
            onClick={() => table.setPageIndex(0)}
            disabled={!table.getCanPreviousPage()}
          >
            <span className="sr-only">首页</span>
            <IconChevronsLeft />
          </Button>
          <Button
            variant="outline"
            className="size-8"
            size="icon"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            <span className="sr-only">上一页</span>
            <IconChevronLeft />
          </Button>
          <Button
            variant="outline"
            className="size-8"
            size="icon"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            <span className="sr-only">下一页</span>
            <IconChevronRight />
          </Button>
          <Button
            variant="outline"
            className="hidden size-8 lg:flex"
            size="icon"
            onClick={() => table.setPageIndex(table.getPageCount() - 1)}
            disabled={!table.getCanNextPage()}
          >
            <span className="sr-only">末页</span>
            <IconChevronsRight />
          </Button>
        </div>
      </div>
    </div>
  )
}

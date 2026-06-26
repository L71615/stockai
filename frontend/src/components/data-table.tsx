"use client"

import * as React from "react"
import { useState, useEffect } from "react"
import { apiGet } from "@/lib/auth"
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
} from "@tanstack/react-table"
import { Area, AreaChart, Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { KlineChart } from "./KlineChart"
import { toast } from "sonner"
import { z } from "zod"

import { useIsMobile } from "@/hooks/use-mobile"
import type { KlineResponse } from "@/lib/api-types"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
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
import { cn } from "@/lib/utils"
import {
  createHoldingRowActionHandlers,
  getHoldingRowActionLabels,
  type HoldingRowActionCallbacks,
} from "@/lib/holding-row-actions"
import {
  IconGripVertical,
  IconTrendingUp,
  IconTrendingDown,
  IconDotsVertical,
  IconLayoutColumns,
  IconChevronDown,
  IconChevronsLeft,
  IconChevronLeft,
  IconChevronRight,
  IconChevronsRight,
} from "@tabler/icons-react"


export const schema = z.object({
  id: z.number(),
  code: z.string(),
  name: z.string(),
  shares: z.string(),
  price: z.string(),
  cost: z.string(),
  pnl: z.string(),
  pnlPct: z.string(),
})

type HoldingRow = z.infer<typeof schema>
type HoldingRowActionMap = Partial<HoldingRowActionCallbacks<HoldingRow>>

function DragHandle({ id }: { id: number }) {
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

function buildColumns(activeActions?: HoldingRowActionMap): ColumnDef<HoldingRow>[] {
  return [
  {
    id: "drag",
    header: () => null,
    cell: ({ row }) => <DragHandle id={row.original.id} />,
  },
  {
    id: "select",
    header: ({ table }) => (
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
    ),
    cell: ({ row }) => (
      <div className="flex items-center justify-center">
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          aria-label="选择行"
        />
      </div>
    ),
    enableSorting: false,
    enableHiding: false,
  },
  {
    accessorKey: "code",
    header: "代码",
    cell: ({ row }) => (
      <span className="font-mono text-xs">{row.original.code}</span>
    ),
    enableHiding: false,
  },
  {
    accessorKey: "name",
    header: "名称",
    cell: ({ row }) => {
      return <StockDetailDrawer item={row.original} />
    },
    enableHiding: false,
  },
  {
    accessorKey: "shares",
    header: () => <div className="w-full text-right">持仓(股)</div>,
    cell: ({ row }) => (
      <div className="text-right font-mono tabular-nums">{row.original.shares}</div>
    ),
  },
  {
    accessorKey: "price",
    header: () => <div className="w-full text-right">现价</div>,
    cell: ({ row }) => (
      <div className="text-right font-mono tabular-nums">{row.original.price}</div>
    ),
  },
  {
    accessorKey: "cost",
    header: () => <div className="w-full text-right">成本</div>,
    cell: ({ row }) => (
      <div className="text-right font-mono tabular-nums text-muted-foreground">
        {row.original.cost}
      </div>
    ),
  },
  {
    accessorKey: "pnl",
    header: () => <div className="w-full text-right">盈亏</div>,
    cell: ({ row }) => {
      const isUp = row.original.pnl.startsWith("+")
      return (
        <div
          className={cn(
            "text-right font-mono tabular-nums font-medium",
            isUp ? "text-red-500" : "text-emerald-500"
          )}
        >
          {row.original.pnl}
        </div>
      )
    },
  },
  {
    accessorKey: "pnlPct",
    header: () => <div className="w-full text-right">盈亏%</div>,
    cell: ({ row }) => {
      const isUp = row.original.pnlPct.startsWith("+")
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
          {row.original.pnlPct}
        </Badge>
      )
    },
  },
  {
    id: "actions",
    cell: ({ row }) => {
      const item = row.original
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
              <span className="sr-only">鎿嶄綔</span>
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
    },
  },
]
}

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

export function DataTable({
  data: initialData,
  actions,
}: {
  data: HoldingRow[]
  actions?: HoldingRowActionMap
}) {
  const [data, setData] = React.useState(() => initialData)
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

  return (
    <Tabs defaultValue="holdings" className="w-full flex-col justify-start gap-6">
      <div className="flex items-center justify-between px-4 lg:px-6">
        <Label htmlFor="view-selector" className="sr-only">视图</Label>
        <Select defaultValue="holdings">
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
            盈利 <Badge variant="secondary" className="text-red-500">{data.filter((d) => d.pnl.startsWith("+")).length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="loss">
            亏损 <Badge variant="secondary" className="text-emerald-500">{data.filter((d) => d.pnl.includes("-")).length}</Badge>
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
      <TabsContent value="holdings" className="relative flex flex-col gap-4 overflow-auto px-4 lg:px-6">
        <div className="overflow-hidden rounded-none border">
          <DndContext
            collisionDetection={closestCenter}
            modifiers={[restrictToVerticalAxis]}
            onDragEnd={handleDragEnd}
            sensors={sensors}
            id={sortableId}
          >
            <Table>
              <TableHeader className="sticky top-0 z-10 bg-muted">
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => {
                      return (
                        <TableHead key={header.id} colSpan={header.colSpan}>
                          {header.isPlaceholder
                            ? null
                            : flexRender(
                                header.column.columnDef.header,
                                header.getContext()
                              )}
                        </TableHead>
                      )
                    })}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody className="**:data-[slot=table-cell]:first:w-8">
                {table.getRowModel().rows?.length ? (
                  <SortableContext
                    items={dataIds}
                    strategy={verticalListSortingStrategy}
                  >
                    {table.getRowModel().rows.map((row) => (
                      <DraggableRow key={row.id} row={row} />
                    ))}
                  </SortableContext>
                ) : (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="h-24 text-center">
                      暂无数据
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </DndContext>
        </div>
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
      </TabsContent>
      <TabsContent value="profit" className="relative flex flex-col gap-4 overflow-auto px-4 lg:px-6">
        <div className="overflow-hidden rounded-none border">
          <DndContext
            collisionDetection={closestCenter}
            modifiers={[restrictToVerticalAxis]}
            onDragEnd={handleDragEnd}
            sensors={sensors}
            id={`${sortableId}-profit`}
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
              <TableBody>
                {table.getRowModel().rows.filter((row) => row.original.pnl.startsWith("+")).length ? (
                  table.getRowModel().rows
                    .filter((row) => row.original.pnl.startsWith("+"))
                    .map((row) => (
                      <TableRow key={`profit-${row.id}`}>
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="h-24 text-center">
                      暂无盈利持仓
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </DndContext>
        </div>
      </TabsContent>
      <TabsContent value="loss" className="relative flex flex-col gap-4 overflow-auto px-4 lg:px-6">
        <div className="overflow-hidden rounded-none border">
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
              {table.getRowModel().rows.filter((row) => row.original.pnl.includes("楼 -")).length ? (
                table.getRowModel().rows
                  .filter((row) => row.original.pnl.includes("楼 -"))
                  .map((row) => (
                    <TableRow key={`loss-${row.id}`}>
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
              ) : (
                <TableRow>
                  <TableCell colSpan={columns.length} className="h-24 text-center">
                    暂无亏损持仓
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </TabsContent>
    </Tabs>
  )
}

// --- Stock detail drawer with mini chart ---

function StockDetailDrawer({ item }: { item: z.infer<typeof schema> }) {
  const isMobile = useIsMobile()
  const [period, setPeriod] = useState("1m")
  const [chartData, setChartData] = useState<KlineResponse | null>(null)
  const [chartLoading, setChartLoading] = useState(false)

  useEffect(() => {
    if (!item.code) return
    setChartLoading(true)
    apiGet<KlineResponse>("/api/stocks/kline/" + item.code + "?period=" + period)
      .then((raw) => setChartData(raw))
      .catch(() => {})
      .finally(() => setChartLoading(false))
  }, [item.code, period])

  const pers = [
    { k: "5d", l: "5日" },
    { k: "1m", l: "1月" },
    { k: "3m", l: "3月" },
    { k: "6m", l: "6月" },
  ]

  return (
    <Drawer direction={isMobile ? "bottom" : "right"}>
      <DrawerTrigger asChild>
        <Button variant="link" className="w-fit px-0 text-left text-foreground font-medium">{item.name}</Button>
      </DrawerTrigger>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle className="font-mono">{item.code} {item.name}</DrawerTitle>
          <DrawerDescription className="sr-only">股票详情与K线图表</DrawerDescription>
        </DrawerHeader>
        <div className="flex flex-col gap-2 overflow-y-auto px-4 text-sm">
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div><span className="text-muted-foreground">现价</span> <span className="font-mono ml-1">{item.price}</span></div>
            <div><span className="text-muted-foreground">成本</span> <span className="font-mono ml-1">{item.cost}</span></div>
            <div><span className="text-muted-foreground">持仓</span> <span className="font-mono ml-1">{item.shares}</span></div>
            <div><span className={cn("font-mono", String(item.pnl).startsWith("+") ? "text-red-500" : String(item.pnl).startsWith("-") ? "text-emerald-500" : "")}>{item.pnl} ({item.pnlPct})</span></div>
          </div>
          <Separator />
          <div className="flex gap-1">
            {pers.map((p) => (
              <button key={p.k} onClick={() => setPeriod(p.k)} className={cn("px-3 py-1 text-xs border-b-2", period === p.k ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>{p.l}</button>
            ))}
          </div>
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
            <span><span className="inline-block w-3 h-0.5 bg-amber-500 align-middle mr-0.5" />MA5</span>
            <span><span className="inline-block w-3 h-0.5 bg-purple-500 align-middle mr-0.5" />MA10</span>
            <span><span className="inline-block w-3 h-0.5 bg-cyan-500 align-middle mr-0.5" />MA20</span>
          </div>
          {chartLoading ? (
            <div className="space-y-2"><Skeleton className="h-[260px] w-full" /><Skeleton className="h-[70px] w-full" /></div>
          ) : !chartData?.dates?.length ? (
            <p className="text-xs text-muted-foreground text-center py-12">暂无数据</p>
          ) : (
            <>
              <KlineChart rawData={chartData} height={260} showIndicatorSelector={false} />
              <KlineChart rawData={chartData} height={70} showIndicatorSelector={false} />
            </>
          )}
        </div>
        <DrawerFooter>
        <DrawerClose asChild>
          <Button variant="outline" size="sm">关闭</Button>
          </DrawerClose>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  )
}


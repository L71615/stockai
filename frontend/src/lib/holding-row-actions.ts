export type HoldingRowActionItem = {
  code: string
  name: string
}

export type HoldingRowActionCallbacks<T extends HoldingRowActionItem> = {
  onEdit: (item: T) => void
  onView: (item: T) => void
  onAddToWatchlist: (item: T) => void
  onDelete: (item: T) => void
}

export function getHoldingRowActionLabels(): string[] {
  return ["编辑", "查看详情", "加入自选", "删除"]
}

export function createHoldingRowActionHandlers<T extends HoldingRowActionItem>(
  item: T,
  callbacks: HoldingRowActionCallbacks<T>
) {
  return {
    edit: () => callbacks.onEdit(item),
    view: () => callbacks.onView(item),
    addToWatchlist: () => callbacks.onAddToWatchlist(item),
    delete: () => callbacks.onDelete(item),
  }
}

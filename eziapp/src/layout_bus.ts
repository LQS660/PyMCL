/**
 * 「编辑布局」入口的中转：侧栏按钮 / 设置页都可能在启动页还没挂载时点下来。
 * 挂载中的画布注册到这里；没有画布时记一个待办标记，启动页装好后自己领走。
 * 单独成一个极小模块，入口包（main.ts）不必为此把整个 dashboard chunk 拽进来。
 */

let pending = false;
let enterEdit: (() => void) | null = null;

/** 启动页挂载画布时注册；卸载时传 null。返回值 = 是否有待办的编辑请求。 */
export function attachLayoutEditor(fn: (() => void) | null): boolean {
  enterEdit = fn;
  if (fn && pending) {
    pending = false;
    fn();
    return true;
  }
  return false;
}

/** 请求进入编辑模式。画布在就直接进；不在就记下，由调用方负责切到启动页。 */
export function requestLayoutEdit(): boolean {
  if (enterEdit) {
    enterEdit();
    return true;
  }
  pending = true;
  return false;
}

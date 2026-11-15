/**
 * PDF 编辑器样式
 */
import { CSSProperties } from 'react'

export const editorStyles = {
  // 主容器
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    position: 'relative',
    overflow: 'hidden',
  } as CSSProperties,

  // 滚动区域 - PDF 预览容器
  scrollArea: {
    flex: 1,
    overflow: 'auto',
    padding: '0',
    paddingBottom: '40px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'flex-start',
    gap: '12px',
    background: 'transparent',
  } as CSSProperties,

  // 页面容器
  pageContainer: {
    position: 'relative',
    backgroundColor: 'white',
    boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05), 0 4px 24px rgba(0, 0, 0, 0.08), 0 1px 0 rgba(0, 0, 0, 0.04)',
    borderRadius: '2px',
  } as CSSProperties,

  // PDF Canvas
  pdfCanvas: {
    display: 'block',
  } as CSSProperties,

  // TextLayer 容器
  textLayerContainer: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    overflow: 'hidden',
    opacity: 0.2,
    lineHeight: 1,
    pointerEvents: 'none',
  } as CSSProperties,

  // 编辑覆盖层
  editOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    pointerEvents: 'none', // 默认不拦截事件
  } as CSSProperties,

  // 可点击的文本区域
  clickableText: {
    position: 'absolute',
    cursor: 'text',
    pointerEvents: 'auto',
    backgroundColor: 'transparent',
    transition: 'background-color 0.15s',
  } as CSSProperties,

  // 悬停状态
  clickableTextHover: {
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
  } as CSSProperties,

  // 可编辑文本输入框
  editableInput: {
    position: 'absolute',
    border: '2px solid #2563eb',
    borderRadius: '2px',
    backgroundColor: 'white',
    padding: '2px 4px',
    outline: 'none',
    boxShadow: '0 2px 8px rgba(37, 99, 235, 0.3)',
    zIndex: 10,
    pointerEvents: 'auto',
  } as CSSProperties,

  // 加载状态
  loadingOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    background: 'linear-gradient(135deg, rgba(102, 126, 234, 0.95) 0%, rgba(118, 75, 162, 0.95) 50%, rgba(240, 147, 251, 0.95) 100%)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 50,
  } as CSSProperties,

  // 工具提示
  tooltip: {
    position: 'fixed',
    padding: '6px 10px',
    backgroundColor: '#1f2937',
    color: 'white',
    fontSize: '12px',
    borderRadius: '4px',
    pointerEvents: 'none',
    zIndex: 100,
    whiteSpace: 'nowrap',
  } as CSSProperties,
}

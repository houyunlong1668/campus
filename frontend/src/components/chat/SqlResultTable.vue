<script setup lang="ts">
import type { SqlResultEvent } from '../../types'

const props = defineProps<{ result: SqlResultEvent }>()
</script>

<template>
  <div class="sql-block">
    <div v-if="!props.result.rows.length" class="sql-empty">没有查到数据</div>
    <div v-else class="sql-scroll">
      <table class="sql-table">
        <thead>
          <tr><th v-for="c in props.result.columns" :key="c">{{ c }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in props.result.rows" :key="i">
            <td v-for="(cell, j) in row" :key="j">{{ cell ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="props.result.truncated" class="sql-trunc">仅显示前 50 行</p>

    <!-- SQL 外显是 spec 的设计原则 3：能看见机器在做什么，也是唯一能发现"查错了"的证据 -->
    <details class="sql-details">
      <summary>查看用到的查询</summary>
      <pre class="sql-code"><code>{{ props.result.sql }}</code></pre>
    </details>
  </div>
</template>

<style scoped>
.sql-block {
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--paper);
  padding: 8px 10px;
}

.sql-empty {
  font-size: 12.5px;
  color: var(--faint);
}

.sql-scroll {
  max-height: 220px;
  overflow: auto;
}

.sql-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.sql-table th,
.sql-table td {
  text-align: left;
  padding: 5px 8px;
  border-bottom: 1px solid var(--rule);
  white-space: nowrap;
}

.sql-table th {
  position: sticky;
  top: 0;
  background: var(--card);
  color: var(--ink);
  font-weight: 600;
}

.sql-trunc {
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--faint);
}

.sql-details {
  margin-top: 8px;
}

.sql-details summary {
  font-size: 12px;
  color: var(--ink-2);
  cursor: pointer;
}

.sql-code {
  margin-top: 6px;
  padding: 8px;
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  font-family: var(--mono);
  font-size: 11.5px;
  white-space: pre-wrap;
  word-break: break-all;
  overflow-x: auto;
}
</style>

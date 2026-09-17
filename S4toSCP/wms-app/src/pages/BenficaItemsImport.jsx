import { useMemo, useState } from 'react'
import { benficaItemsApi } from '../services/api'
import { useToast } from '../context/ToastContext'
import {
  Badge, Btn, Card, CardTitle, ResultBanner, Spinner, Stat, StatsBar,
} from '../components/ui'
import styles from './BenficaItemsImport.module.css'

export default function BenficaItemsImport() {
  const toast = useToast()
  const [loading, setLoading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [preview, setPreview] = useState(null)
  const [result, setResult] = useState(null)
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')

  const handleFile = async (file) => {
    if (!file?.name?.toUpperCase().match(/\.(XLSX|XLS)$/)) {
      toast('O ficheiro deve ser Excel (.xlsx)', 'error')
      return
    }

    setLoading(true)
    setResult(null)
    try {
      const data = await benficaItemsApi.preview(file)
      setPreview(data)
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      setLoading(false)
      setDragging(false)
    }
  }

  const filteredRows = useMemo(() => {
    const rows = preview?.rows ?? []
    const query = search.trim().toLowerCase()

    return rows.filter((row) => {
      if (filter === 'new' && (row.exists_in_db || row.duplicate_in_file)) return false
      if (filter === 'existing' && !row.exists_in_db) return false
      if (filter === 'duplicate' && !row.duplicate_in_file) return false

      if (!query) return true

      return [
        row.item_id,
        row.barcode,
        row.client_ref,
        row.item_desc,
        row.size_id,
      ].some((value) => (value || '').toLowerCase().includes(query))
    })
  }, [filter, preview, search])

  const rowsToImport = useMemo(
    () => (preview?.rows ?? []).filter((row) => !row.exists_in_db && !row.duplicate_in_file),
    [preview]
  )

  const reset = () => {
    setPreview(null)
    setResult(null)
    setFilter('all')
    setSearch('')
    setDragging(false)
  }

  const doImport = async () => {
    if (!rowsToImport.length) {
      toast('Nao existem artigos novos para importar.', 'error')
      return
    }

    setLoading(true)
    try {
      const importResult = await benficaItemsApi.import(rowsToImport)
      setResult(importResult)
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  const stopDefaults = (event) => {
    event.preventDefault()
    event.stopPropagation()
  }

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Import Artigos Benfica</h1>
        <p className={styles.pageDesc}>Importação de artigos SLB a partir de Excel com controlo por barcode.</p>
      </div>

      {!preview && (
        <Card>
          <CardTitle>Ficheiro Excel</CardTitle>
          <div
            className={`${styles.dropZone} ${dragging ? styles.dropActive : ''} ${loading ? styles.dropLoading : ''}`}
            onClick={() => document.getElementById('benficaItemsInput').click()}
            onDragEnter={(event) => {
              stopDefaults(event)
              setDragging(true)
            }}
            onDragOver={stopDefaults}
            onDragLeave={(event) => {
              stopDefaults(event)
              setDragging(false)
            }}
            onDrop={(event) => {
              stopDefaults(event)
              handleFile(event.dataTransfer.files?.[0])
            }}
          >
            <input
              id="benficaItemsInput"
              type="file"
              accept=".xlsx,.xls"
              style={{ display: 'none' }}
              onChange={(event) => handleFile(event.target.files?.[0])}
            />
            {loading ? (
              <>
                <Spinner size={32} />
                <p className={styles.loadingText}>A processar ficheiro...</p>
              </>
            ) : (
              <>
                <div className={styles.dropIcon}>SLB</div>
                <h3 className={styles.dropTitle}>Arraste o ficheiro Excel ou clique para selecionar</h3>
                <p className={styles.dropDesc}>Colunas usadas: A Cliente Ref, C Descrição, D Barcode, E Preço Sócio, F Preço PVP.</p>
              </>
            )}
          </div>
        </Card>
      )}

      {preview && (
        <>
          <StatsBar>
            <Stat label="Linhas" value={preview.total_lines} />
            <Stat label="Barcodes únicos" value={preview.unique_barcodes} />
            <Stat label="Novos" value={preview.new_items} color="var(--green)" />
            <Stat label="Já existentes" value={preview.existing_items} color="var(--accent)" />
            <Stat label="Duplicadas" value={preview.duplicate_rows} color="var(--yellow)" />
          </StatsBar>

          <div className={styles.actions}>
            <Btn variant="outline" onClick={reset}>← Novo ficheiro</Btn>
            <Btn variant="success" onClick={doImport} loading={loading} disabled={!rowsToImport.length}>
              Importar {rowsToImport.length} artigo(s) →
            </Btn>
          </div>

          {result && (
            <ResultBanner
              ok={result.created > 0}
              title={result.created > 0 ? 'Importacao concluida' : 'Nenhum artigo novo criado'}
              detail={`Criados: ${result.created}. Ignorados existentes: ${result.skipped_existing}. Ignorados duplicados: ${result.skipped_duplicates}.`}
            />
          )}

          <Card>
            <CardTitle>Resumo do ficheiro</CardTitle>
            <div className={styles.tableFilters}>
              {[
                ['all', 'Todos'],
                ['new', 'Novos'],
                ['existing', 'Existentes'],
                ['duplicate', 'Duplicados'],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`${styles.filterBtn} ${filter === value ? styles.filterActive : ''}`}
                  onClick={() => setFilter(value)}
                >
                  {label}
                </button>
              ))}
              <input
                className={styles.searchInput}
                placeholder="Pesquisar..."
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>

            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Código</th>
                    <th>Ref. Cliente</th>
                    <th>Descrição</th>
                    <th>Barcode</th>
                    <th>Tamanho</th>
                    <th>Preço Sócio</th>
                    <th>Preço PVP</th>
                    <th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.map((row, index) => {
                    const isNew = !row.exists_in_db && !row.duplicate_in_file
                    const status = row.duplicate_in_file ? 'Duplicado no ficheiro' : row.exists_in_db ? 'Já existe' : 'Novo'
                    const badgeType = row.duplicate_in_file ? 'warn' : row.exists_in_db ? 'exists' : 'new'

                    return (
                      <tr key={`${row.barcode}-${index}`}>
                        <td className={styles.mono}>{row.item_id}</td>
                        <td className={styles.mono}>{row.client_ref}</td>
                        <td className={styles.desc}>{row.item_desc}</td>
                        <td className={styles.mono}>{row.barcode}</td>
                        <td><span className={styles.sizePill}>{row.size_id || '—'}</span></td>
                        <td className={styles.mono}>{row.price_socio || '—'}</td>
                        <td className={styles.mono}>{row.price_pvp || '—'}</td>
                        <td>
                          <div className={styles.statusCell}>
                            <Badge type={badgeType}>{status}</Badge>
                            {!isNew && row.existing_item_id && !row.duplicate_in_file && (
                              <span className={styles.statusMeta}>{row.existing_item_id}</span>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}

from __future__ import annotations
"""
Resolve o ItemID correto para cada linha do CSV do packing list
usando a encomenda ESCP selecionada.
"""
import logging
import unicodedata
import re
from app.db.connection import db_cursor

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """
    Normaliza texto para comparação flexível:
    - Remove acentos e diacríticos
    - Converte para maiúsculas
    - Substitui caracteres não alfanuméricos por espaço
    - Colapsa espaços múltiplos
    """
    # Remove acentos (NFD decompose + remove combining chars)
    nfd = unicodedata.normalize('NFD', str(text))
    without_accents = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
    # Maiúsculas e substitui não-alfanuméricos por espaço
    cleaned = re.sub(r'[^A-Z0-9]', ' ', without_accents.upper())
    # Colapsa espaços múltiplos
    return re.sub(r'\s+', ' ', cleaned).strip()


def resolve_item_ids(order_id: int, csv_rows: list) -> tuple[list, list[str]]:
    # Carrega todas as linhas da encomenda de uma vez
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT ItemID, RefCli
            FROM ClientOrderDetails
            WHERE OrderID = ? AND DocType = 'ESCP'
        """, (order_id,))
        order_lines = cursor.fetchall()

    logger.info(f"Encomenda {order_id}: {len(order_lines)} linhas carregadas")

    # Índice duplo: exato e normalizado
    ref_to_items: dict[str, list[str]]      = {}   # {ref_cli_original: [item_ids]}
    ref_norm_to_items: dict[str, list[str]] = {}   # {ref_cli_normalizado: [item_ids]}

    for item_id, ref_cli in order_lines:
        key      = str(ref_cli).strip()
        key_norm = _normalize(key)
        ref_to_items.setdefault(key, []).append(str(item_id).strip())
        ref_norm_to_items.setdefault(key_norm, []).append(str(item_id).strip())

    logger.info(f"RefCli disponíveis: {list(ref_to_items.keys())[:10]}")

    errors  = []
    updated = []

    from app.models.schemas import CSVRow

    for row in csv_rows:
        # Linha já resolvida (match automático anterior ou completada manualmente
        # pelo operador) — não reprocessa, preserva a escolha feita.
        if row.resolved:
            updated.append(row)
            continue

        prefix    = f"MESCP{row.style_code}-{row.color_code}-{row.size}"
        ref       = str(row.season_desc).strip()
        ref_norm  = _normalize(ref)

        # 1. Tenta match exato
        candidates = ref_to_items.get(ref, [])

        # 2. Tenta match normalizado (sem acentos, case-insensitive)
        if not candidates:
            candidates = ref_norm_to_items.get(ref_norm, [])
            if candidates:
                logger.info(f"Match normalizado: '{ref}' → '{ref_norm}'")

        # 3. Tenta match por palavras (ignora caracteres corrompidos como ?)
        #    Usa score proporcional para desempatar: palavras comuns / palavras da ref
        if not candidates:
            ref_words  = set(re.findall(r'[A-Z0-9]+', ref_norm))
            best_score = 0
            best_key   = None
            best_cands = []
            for norm_key, items in ref_norm_to_items.items():
                key_words = set(re.findall(r'[A-Z0-9]+', norm_key))
                common = ref_words & key_words
                # Score = palavras em comum, desempate por proporção
                score = len(common) + len(common) / max(len(key_words), 1)
                # Verifica também se algum candidato começa com o prefix
                has_prefix = any(iid.startswith(prefix) for iid in items)
                if has_prefix:
                    score += 10  # prioridade forte se o prefix bate
                if len(common) >= 2 and score > best_score:
                    best_score = score
                    best_key   = norm_key
                    best_cands = items
            if best_key:
                candidates = best_cands
                logger.info(f"Match por palavras (score={best_score:.1f}): '{ref}' → '{best_key}'")

        match = next((iid for iid in candidates if iid.startswith(prefix)), None)

        if not match:
            logger.warning(
                f"Sem match: prefix='{prefix}' ref='{ref}' norm='{ref_norm}' "
                f"candidates={candidates[:3]}"
            )
            # Não foi possível ligar a linha à encomenda ESCP de origem — o código
            # gerado a partir do CSV (style+cor+tam) fica incompleto porque falta o
            # sufixo real do artigo (ex: -DOT, -NEG), que só existe na encomenda.
            # A linha fica marcada como não resolvida: o operador tem de completar
            # manualmente (escolhendo um candidato ou indicando o código correto)
            # antes de poder ser importada — caso contrário é excluída da importação.
            errors.append(
                f"Artigo não encontrado na encomenda: "
                f"style={row.style_code}, color={row.color_code}, "
                f"size={row.size}, PO='{ref}'"
                + (f" — candidatos com a mesma referência: {', '.join(sorted(set(candidates))[:5])}" if candidates else "")
            )
            row_dict = row.dict()
            row_dict['resolved'] = False
            row_dict['candidate_item_ids'] = sorted(set(candidates))[:10]
            updated.append(CSVRow(**row_dict))
        else:
            row_dict = row.dict()
            row_dict['item_id'] = match
            row_dict['resolved'] = True
            row_dict['candidate_item_ids'] = []
            updated.append(CSVRow(**row_dict))

    return updated, errors

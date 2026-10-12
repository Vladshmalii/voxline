import { useState, useEffect, useCallback } from 'react';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { resolveText } from 'i18n';
import { Modal } from 'components/Modal';
import { RefreshButton } from 'components/RefreshButton';
import { toast } from 'components/Toaster';
import { ResourceForm, buildInitialValues, buildPayload } from 'components/ResourceForm';
import {
  PageContent,
  HeaderSection,
  PageTitle,
  HeaderActions,
  ContentScroll,
  PrimaryButton,
  SecondaryButton,
  DangerButton,
  TableContainer,
  Table,
  TableHeader,
  TableHeaderCell,
  TableRow,
  TableCell,
  EmptyState,
  EmptyStateTitle,
  EmptyStateText,
  RowActions,
  RowActionButton,
} from 'components/ui';

/**
 * Generic CRUD page of the call panel.
 *
 * Text slots accept either a literal or an i18n key: `title`/`titleKey`,
 * `emptyText`/`emptyTextKey`, and per column `label`/`labelKey`.
 *
 * props:
 *   title        — tab heading
 *   api          — { list, create?, update?, get?, remove? } from utils/callApi
 *   columns      — [{ key, label, align?, render?(row) }]
 *   loadDetail   — the list rows are a lightweight projection, so fetch the
 *                  full row via api.get(id) before opening the edit form
 *   fields       — form spec for create/edit (see ResourceForm);
 *                  createOnly: true — the field only appears in the create
 *                  form (the backend's PATCH schema rejects it)
 *   rowActions   — [{ key, label, danger?, refresh?, confirm?,
 *                     run(row) → Promise, successMessage?(result, row) }]
 *   onRowClick   — (row) => void; makes the whole row clickable (the buttons in
 *                  the actions cell keep working — their clicks don't bubble)
 *   rowClickEdit — clicking a row opens the edit form; the standalone Edit
 *                  button is dropped, since the row itself is the affordance
 *   headerExtra  — extra controls in the header
 *   wideModal    — render the form modal wide
 *   refreshKey   — changing it reloads the list (rows mutated elsewhere)
 *   onFormValues — called with the form values whenever they change (and when
 *                  a form opens/closes, the latter with null); for a page whose
 *                  field options depend on what is selected in the form
 *   readOnly     — suppresses create/edit/delete and every rowAction, for a
 *                  role that may view this resource but not write it
 *   canDelete    — narrower than readOnly: defaults to !readOnly, but a role
 *                  that can create/edit may still not be allowed to delete
 *                  (VOAD-57: staff can manage agents but not remove them)
 */
export const CrudPage = ({
  title,
  titleKey,
  api,
  columns,
  fields,
  rowActions = [],
  onRowClick,
  rowClickEdit = false,
  headerExtra = null,
  wideModal = false,
  loadDetail = false,
  emptyText,
  emptyTextKey,
  refreshKey = 0,
  onFormValues,
  readOnly = false,
  canDelete = !readOnly,
}) => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const heading = titleKey ? t(titleKey) : title;
  const empty = emptyTextKey ? t(emptyTextKey) : emptyText || t('common.nothingHere');
  const [rows, setRows] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState(null); // { mode: 'create'|'edit', row? }
  const [formValues, setFormValues] = useState({});
  const [formErrors, setFormErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(null); // row pending delete confirm
  const [busyAction, setBusyAction] = useState(null); // `${rowId}:${actionKey}`

  const reload = useCallback(() => {
    setLoadError(null);
    setLoading(true);
    api
      .list()
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((e) => {
        setLoadError(e.message);
        setRows([]);
      })
      .finally(() => setLoading(false));
  }, [api]);

  useEffect(() => {
    reload();
  }, [reload, refreshKey]);

  const editFields = fields ? fields.filter((f) => !f.createOnly) : fields;

  const updateFormValues = (next) => {
    setFormValues(next);
    if (onFormValues) onFormValues(next);
  };

  const closeModal = () => {
    setModal(null);
    if (onFormValues) onFormValues(null);
  };

  const openCreate = () => {
    updateFormValues(buildInitialValues(fields, null));
    setFormErrors({});
    setModal({ mode: 'create' });
  };

  const openEdit = async (row) => {
    // The list may be a lightweight projection (e.g. a messanger integration
    // without its `auth`); pull the full row so the form prefills every field.
    let detail = row;
    if (loadDetail && api.get) {
      setBusyAction(`${row.id}:edit`);
      try {
        detail = await api.get(row.id);
      } catch (e) {
        toast(e.message, 'error');
        setBusyAction(null);
        return;
      }
      setBusyAction(null);
    }
    updateFormValues(buildInitialValues(editFields, detail));
    setFormErrors({});
    setModal({ mode: 'edit', row: detail });
  };

  const submitForm = async () => {
    const modalFields = modal.mode === 'create' ? fields : editFields;
    const { payload, errors } = buildPayload(modalFields, formValues);
    setFormErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSaving(true);
    try {
      if (modal.mode === 'create') {
        await api.create(payload);
        toast(t('common.created'), 'success');
      } else {
        await api.update(modal.row.id, payload);
        toast(t('common.saved'), 'success');
      }
      closeModal();
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    const row = deleting;
    setSaving(true);
    try {
      await api.remove(row.id);
      toast(t('common.deleted'), 'success');
      setDeleting(null);
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const runRowAction = async (action, row) => {
    const busyKey = `${row.id}:${action.key}`;
    setBusyAction(busyKey);
    try {
      const result = await action.run(row);
      if (!action.silent) {
        const message = action.successMessage ? action.successMessage(result, row) : t('common.done');
        toast(message, 'success');
      }
      if (action.refresh) reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setBusyAction(null);
    }
  };

  // rowClickEdit turns the row into the edit affordance, so the button is gone.
  const hasEdit = !readOnly && Boolean(api.update && fields) && !rowClickEdit;
  const hasDelete = canDelete && Boolean(api.remove);
  const effectiveRowActions = readOnly ? [] : rowActions;
  const hasActionsColumn = hasEdit || hasDelete || effectiveRowActions.length > 0;
  const rowClick = onRowClick || (rowClickEdit && !readOnly ? openEdit : null);

  return (
    <PageContent>
      <HeaderSection theme={theme}>
        <PageTitle theme={theme}>{heading}</PageTitle>
        <HeaderActions>
          {!readOnly && api.create && fields && (
            <PrimaryButton theme={theme} type="button" onClick={openCreate}>
              + {t('common.create')}
            </PrimaryButton>
          )}
          {headerExtra}
          <RefreshButton onClick={reload} loading={loading} />
        </HeaderActions>
      </HeaderSection>

      <ContentScroll theme={theme}>
        {rows === null ? (
          <EmptyState theme={theme}>{t('common.loading')}</EmptyState>
        ) : loadError ? (
          <EmptyState theme={theme}>
            <EmptyStateTitle theme={theme}>{t('common.failedToLoad')}</EmptyStateTitle>
            <EmptyStateText theme={theme}>{loadError}</EmptyStateText>
          </EmptyState>
        ) : rows.length === 0 ? (
          <EmptyState theme={theme}>
            <EmptyStateTitle theme={theme}>{t('common.noData')}</EmptyStateTitle>
            <EmptyStateText theme={theme}>{empty}</EmptyStateText>
          </EmptyState>
        ) : (
          <TableContainer theme={theme}>
            <Table>
              <TableHeader theme={theme}>
                <tr>
                  {columns.map((col) => (
                    <TableHeaderCell key={col.key} theme={theme} $align={col.align}>
                      {resolveText(t, col, 'label')}
                    </TableHeaderCell>
                  ))}
                  {hasActionsColumn && (
                    <TableHeaderCell theme={theme} $align="right">
                      {t('common.actions')}
                    </TableHeaderCell>
                  )}
                </tr>
              </TableHeader>
              <tbody>
                {rows.map((row) => (
                  <TableRow
                    key={row.id}
                    theme={theme}
                    onClick={rowClick ? () => rowClick(row) : undefined}
                    style={rowClick ? { cursor: 'pointer' } : undefined}
                  >
                    {columns.map((col) => (
                      <TableCell key={col.key} theme={theme} $align={col.align}>
                        {col.render ? col.render(row) : row[col.key] ?? '—'}
                      </TableCell>
                    ))}
                    {hasActionsColumn && (
                      // Buttons act on their own — a click here must not also
                      // trigger the row.
                      <TableCell theme={theme} $align="right" onClick={(e) => e.stopPropagation()}>
                        <RowActions style={{ justifyContent: 'flex-end' }}>
                          {effectiveRowActions.map((action) => (
                            <RowActionButton
                              key={action.key}
                              theme={theme}
                              type="button"
                              disabled={busyAction === `${row.id}:${action.key}`}
                              onClick={() => runRowAction(action, row)}
                            >
                              {busyAction === `${row.id}:${action.key}`
                                ? '…'
                                : resolveText(t, action, 'label')}
                            </RowActionButton>
                          ))}
                          {hasEdit && (
                            <RowActionButton
                              theme={theme}
                              type="button"
                              disabled={busyAction === `${row.id}:edit`}
                              onClick={() => openEdit(row)}
                            >
                              {busyAction === `${row.id}:edit` ? '…' : t('common.edit')}
                            </RowActionButton>
                          )}
                          {hasDelete && (
                            <RowActionButton
                              theme={theme}
                              type="button"
                              $danger
                              onClick={() => setDeleting(row)}
                            >
                              {t('common.remove')}
                            </RowActionButton>
                          )}
                        </RowActions>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </tbody>
            </Table>
          </TableContainer>
        )}
      </ContentScroll>

      {modal && (
        <Modal
          title={
            modal.mode === 'create'
              ? `${t('common.create')} — ${heading}`
              : `${t('common.edit')} #${modal.row.id} — ${heading}`
          }
          onClose={closeModal}
          wide={wideModal}
          footer={
            <>
              <SecondaryButton theme={theme} type="button" onClick={closeModal}>
                {t('common.cancel')}
              </SecondaryButton>
              <PrimaryButton theme={theme} type="button" disabled={saving} onClick={submitForm}>
                {saving ? t('common.saving') : t('common.save')}
              </PrimaryButton>
            </>
          }
        >
          <ResourceForm
            fields={modal.mode === 'create' ? fields : editFields}
            values={formValues}
            errors={formErrors}
            onChange={updateFormValues}
          />
        </Modal>
      )}

      {deleting && (
        <Modal
          title={`${t('common.remove')} #${deleting.id}?`}
          onClose={() => setDeleting(null)}
          footer={
            <>
              <SecondaryButton theme={theme} type="button" onClick={() => setDeleting(null)}>
                {t('common.cancel')}
              </SecondaryButton>
              <DangerButton theme={theme} type="button" disabled={saving} onClick={confirmDelete}>
                {saving ? t('common.removing') : t('common.remove')}
              </DangerButton>
            </>
          }
        >
          <EmptyStateText theme={theme}>{t('common.irreversible')}</EmptyStateText>
        </Modal>
      )}
    </PageContent>
  );
};

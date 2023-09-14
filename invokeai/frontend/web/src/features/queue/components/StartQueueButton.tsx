import { useAppDispatch } from 'app/store/storeHooks';
import { addToast } from 'features/system/store/systemSlice';
import { memo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { FaPlay } from 'react-icons/fa';
import {
  useGetQueueStatusQuery,
  useStartQueueExecutionMutation,
} from 'services/api/endpoints/queue';
import { useIsQueueMutationInProgress } from '../hooks/useIsQueueMutationInProgress';
import QueueButton from './common/QueueButton';

type Props = {
  asIconButton?: boolean;
};

const StartQueueButton = ({ asIconButton }: Props) => {
  const { data: queueStatusData } = useGetQueueStatusQuery();
  const dispatch = useAppDispatch();
  const { t } = useTranslation();
  const [startQueue] = useStartQueueExecutionMutation({
    fixedCacheKey: 'startQueue',
  });
  const isQueueMutationInProgress = useIsQueueMutationInProgress();

  const handleClick = useCallback(async () => {
    try {
      await startQueue().unwrap();
      dispatch(
        addToast({
          title: t('queue.startSucceeded'),
          status: 'success',
        })
      );
    } catch {
      dispatch(
        addToast({
          title: t('queue.startFailed'),
          status: 'error',
        })
      );
    }
  }, [dispatch, startQueue, t]);

  return (
    <QueueButton
      asIconButton={asIconButton}
      label={t('queue.start')}
      tooltip={t('queue.startTooltip')}
      isDisabled={
        queueStatusData?.started ||
        queueStatusData?.stop_after_current ||
        queueStatusData?.pending === 0 ||
        isQueueMutationInProgress
      }
      icon={<FaPlay />}
      onClick={handleClick}
      colorScheme="green"
    />
  );
};

export default memo(StartQueueButton);

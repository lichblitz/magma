/*
 * Copyright 2020 The Magma Authors.
 *
 * This source code is licensed under the BSD-style license found in the
 * LICENSE file in the root directory of this source tree.
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * @flow strict-local
 * @format
 */

import AsyncMetric from '@fbcnms/ui/insights/AsyncMetric';
import Card from '@material-ui/core/Card';
import CardHeader from '@material-ui/core/CardHeader';
import DataUsageIcon from '@material-ui/icons/DataUsage';
import Grid from '@material-ui/core/Grid';
import React from 'react';
import Text from '../theme/design-system/Text';
import moment from 'moment';

import {CardTitleFilterRow} from './layout/CardTitleRow';
import {DateTimePicker} from '@material-ui/pickers';
import {colors} from '../theme/default';
import {makeStyles} from '@material-ui/styles';
import {useState} from 'react';

export type DateTimeMetricChartProps = {
  title: string,
  queries: Array<string>,
  legendLabels: Array<string>,
};

const useStyles = makeStyles(_ => ({
  dateTimeText: {
    color: colors.primary.comet,
  },
}));

export default function DateTimeMetricChart(props: DateTimeMetricChartProps) {
  const classes = useStyles();
  const [startDate, setStartDate] = useState(moment().subtract(3, 'hours'));
  const [endDate, setEndDate] = useState(moment());

  function Filter() {
    return (
      <Grid container justify="flex-end" alignItems="center" spacing={1}>
        <Grid item>
          <Text variant="body3" className={classes.dateTimeText}>
            Filter By Date
          </Text>
        </Grid>
        <Grid item>
          <DateTimePicker
            autoOk
            variant="outlined"
            inputVariant="outlined"
            maxDate={endDate}
            disableFuture
            value={startDate}
            onChange={setStartDate}
          />
        </Grid>
        <Grid item>
          <Text variant="body3" className={classes.dateTimeText}>
            to
          </Text>
        </Grid>
        <Grid item>
          <DateTimePicker
            autoOk
            variant="outlined"
            inputVariant="outlined"
            disableFuture
            value={endDate}
            onChange={setEndDate}
          />
        </Grid>
      </Grid>
    );
  }

  return (
    <>
      <CardTitleFilterRow
        icon={DataUsageIcon}
        label={props.title}
        filter={Filter}
      />
      <Card elevation={0}>
        <CardHeader
          title={<Text variant="body2">Frequency of {props.title}</Text>}
          subheader={
            <AsyncMetric
              style={{
                data: {
                  lineTension: 0.2,
                  pointRadius: 0.1,
                },
                options: {
                  xAxes: {
                    gridLines: {
                      display: false,
                    },
                    ticks: {
                      maxTicksLimit: 10,
                    },
                  },
                  yAxes: {
                    gridLines: {
                      drawBorder: true,
                    },
                    ticks: {
                      maxTicksLimit: 1,
                    },
                  },
                },
                legend: {
                  position: 'top',
                  align: 'end',
                },
              }}
              label={`Frequency of ${props.title}`}
              unit=""
              queries={props.queries}
              timeRange={'3_hours'}
              startEnd={[startDate, endDate]}
              legendLabels={props.legendLabels}
            />
          }
        />
      </Card>
    </>
  );
}

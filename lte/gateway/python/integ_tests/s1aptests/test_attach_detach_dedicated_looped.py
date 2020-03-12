"""
Copyright (c) 2016-present, Facebook, Inc.
All rights reserved.

This source code is licensed under the BSD-style license found in the
LICENSE file in the root directory of this source tree. An additional grant
of patent rights can be found in the PATENTS file in the same directory.
"""

import unittest
import s1ap_types
import time

from integ_tests.s1aptests import s1ap_wrapper
from integ_tests.s1aptests.s1ap_utils import SpgwUtil


class TestAttachDetachDedicatedLooped(unittest.TestCase):
    def setUp(self):
        self._s1ap_wrapper = s1ap_wrapper.TestWrapper()
        self._spgw_util = SpgwUtil()

    def tearDown(self):
        self._s1ap_wrapper.cleanup()

    def test_attach_detach(self):
        """ attach/detach + dedicated bearer test in loop with a single UE """
        num_ues = 1
        loop = 3
        self._s1ap_wrapper.configUEDevice(num_ues)

        for i in range(num_ues):
            req = self._s1ap_wrapper.ue_req
            print(
                "********************* Running End to End attach for ",
                "UE id ",
                req.ue_id,
            )
            # Now actually complete the attach
            self._s1ap_wrapper._s1_util.attach(
                req.ue_id,
                s1ap_types.tfwCmd.UE_END_TO_END_ATTACH_REQUEST,
                s1ap_types.tfwCmd.UE_ATTACH_ACCEPT_IND,
                s1ap_types.ueAttachAccept_t,
            )

            # Wait on EMM Information from MME
            self._s1ap_wrapper._s1_util.receive_emm_info()

            for j in range(loop):
                time.sleep(2)
                print("*************************************************")
                print("********************* Iteration - ", j + 1)
                print("*************************************************")
                print(
                    "***************** Adding dedicated bearer to IMSI",
                    "".join([str(i) for i in req.imsi]),
                )
                self._spgw_util.create_bearer(
                    "IMSI" + "".join([str(i) for i in req.imsi]), 5
                )

                response = self._s1ap_wrapper.s1_util.get_response()
                self.assertEqual(
                    response.msg_type,
                    s1ap_types.tfwCmd.UE_ACT_DED_BER_REQ.value,
                )
                act_ded_ber_ctxt_req = response.cast(
                    s1ap_types.UeActDedBearCtxtReq_t
                )
                self._s1ap_wrapper.sendActDedicatedBearerAccept(
                    req.ue_id, act_ded_ber_ctxt_req.bearerId
                )

                time.sleep(1)
                print(
                    "*************** Deleting dedicated bearer for IMSI",
                    "".join([str(i) for i in req.imsi]),
                )
                self._spgw_util.delete_bearer(
                    "IMSI" + "".join([str(i) for i in req.imsi]),
                    5,
                    act_ded_ber_ctxt_req.bearerId,
                )

                response = self._s1ap_wrapper.s1_util.get_response()
                self.assertEqual(
                    response.msg_type,
                    s1ap_types.tfwCmd.UE_DEACTIVATE_BER_REQ.value,
                )

                print("************** Received deactivate eps bearer context")

                deactv_bearer_req = response.cast(
                    s1ap_types.UeDeActvBearCtxtReq_t
                )
                self._s1ap_wrapper.sendDeactDedicatedBearerAccept(
                    req.ue_id, deactv_bearer_req.bearerId
                )

            time.sleep(5)
            print(
                "********************** Running UE detach for UE id ",
                req.ue_id,
            )
            # Now detach the UE
            self._s1ap_wrapper.s1_util.detach(
                req.ue_id, s1ap_types.ueDetachType_t.UE_NORMAL_DETACH.value
            )


if __name__ == "__main__":
    unittest.main()
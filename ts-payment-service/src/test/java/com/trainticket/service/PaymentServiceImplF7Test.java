package com.trainticket.service;

import com.trainticket.entity.Payment;
import com.trainticket.repository.AddMoneyRepository;
import com.trainticket.repository.PaymentRepository;
import edu.fudan.common.util.Response;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.HttpHeaders;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class PaymentServiceImplF7Test {

    @Mock
    private PaymentRepository paymentRepository;

    @Mock
    private AddMoneyRepository addMoneyRepository;

    @Mock
    private FeatureFlagService featureFlagService;

    @InjectMocks
    private PaymentServiceImpl paymentService;

    private long timedPay(boolean flag) {
        when(featureFlagService.isEnabled("tt-feat-07")).thenReturn(flag);
        when(paymentRepository.findByOrderId("order-1")).thenReturn(null);
        Payment payment = new Payment();
        payment.setOrderId("order-1");
        payment.setPrice("100.0");
        payment.setUserId("user-1");
        long start = System.nanoTime();
        Response r = paymentService.pay(payment, new HttpHeaders());
        long ms = (System.nanoTime() - start) / 1_000_000;
        assertEquals(1, r.getStatus().intValue());
        return ms;
    }

    @Test
    void flagOffAnswersImmediately() {
        long ms = timedPay(false);
        assertTrue(ms < 500, "took " + ms + " ms");
    }

    @Test
    void flagOnAnswersAfterOneAndAHalfToTwoAndAHalfSeconds() {
        long ms = timedPay(true);
        assertTrue(ms >= 1500 && ms <= 2700, "took " + ms + " ms");
    }
}

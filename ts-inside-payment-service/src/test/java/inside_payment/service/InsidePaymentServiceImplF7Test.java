package inside_payment.service;

import edu.fudan.common.entity.Order;
import edu.fudan.common.entity.OrderStatus;
import edu.fudan.common.util.Response;
import inside_payment.entity.Money;
import inside_payment.entity.PaymentInfo;
import inside_payment.repository.AddMoneyRepository;
import inside_payment.repository.PaymentRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.Collections;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class InsidePaymentServiceImplF7Test {

    private static final String PAYMENT_URL = "http://ts-payment-service/api/v1/paymentservice/payment";

    @Mock
    private RestTemplate restTemplate;

    @Mock
    private PaymentRepository paymentRepository;

    @Mock
    private AddMoneyRepository addMoneyRepository;

    @Mock
    private FeatureFlagService featureFlagService;

    @InjectMocks
    private InsidePaymentServiceImpl service;

    @BeforeEach
    void unpaidOrderAndRichAccount() {
        Order order = new Order();
        order.setStatus(OrderStatus.NOTPAID.getCode());
        order.setPrice("100.0");
        doReturn(new ResponseEntity<>(new Response<>(1, "Success", order), HttpStatus.OK))
                .when(restTemplate).exchange(anyString(), eq(HttpMethod.GET), any(HttpEntity.class), any(ParameterizedTypeReference.class));
        doReturn(new ResponseEntity<>(new Response<>(1, "Success", null), HttpStatus.OK))
                .when(restTemplate).exchange(contains("/status/"), eq(HttpMethod.GET), any(HttpEntity.class), eq(Response.class));
        Money money = new Money();
        money.setUserId("user-1");
        money.setMoney("10000");
        when(paymentRepository.findByUserId("user-1")).thenReturn(new ArrayList<>());
        when(addMoneyRepository.findByUserId("user-1")).thenReturn(Collections.singletonList(money));
    }

    private static PaymentInfo info() {
        PaymentInfo i = new PaymentInfo();
        i.setUserId("user-1");
        i.setOrderId("order-1");
        i.setTripId("G1234");
        return i;
    }

    private void paymentServiceAnswersAfter(long ms) {
        doAnswer(inv -> {
            Thread.sleep(ms);
            return new ResponseEntity<>(new Response<>(1, "Pay Success", null), HttpStatus.OK);
        }).when(restTemplate).exchange(eq(PAYMENT_URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(Response.class));
    }

    @Test
    void flagOffPaysFromBalanceWithoutThirdParty() {
        when(featureFlagService.isEnabled("tt-feat-07")).thenReturn(false);
        Response r = service.pay(info(), new HttpHeaders());
        assertEquals(1, r.getStatus().intValue());
        verify(restTemplate, never()).exchange(eq(PAYMENT_URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(Response.class));
    }

    @Test
    void flagOnForcesThirdPartyAndSucceedsWithinBudget() {
        when(featureFlagService.isEnabled("tt-feat-07")).thenReturn(true);
        paymentServiceAnswersAfter(100);
        Response r = service.pay(info(), new HttpHeaders());
        assertEquals(1, r.getStatus().intValue());
        verify(restTemplate).exchange(eq(PAYMENT_URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(Response.class));
    }

    @Test
    void flagOnFailsWhenThirdPartyExceedsBudget() {
        when(featureFlagService.isEnabled("tt-feat-07")).thenReturn(true);
        paymentServiceAnswersAfter(3000);
        long start = System.nanoTime();
        assertThrows(IllegalStateException.class, () -> service.pay(info(), new HttpHeaders()));
        long ms = (System.nanoTime() - start) / 1_000_000;
        assertTrue(ms < 2800, "took " + ms + " ms");
    }

    @Test
    void flagOffKeepsUnbudgetedCallWhenBalanceIsShort() {
        when(featureFlagService.isEnabled("tt-feat-07")).thenReturn(false);
        when(addMoneyRepository.findByUserId("user-1")).thenReturn(new ArrayList<>());
        paymentServiceAnswersAfter(2500);
        Response r = service.pay(info(), new HttpHeaders());
        assertEquals(1, r.getStatus().intValue());
    }
}

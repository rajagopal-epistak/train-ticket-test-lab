package other.service;

import edu.fudan.common.entity.OrderStatus;
import edu.fudan.common.util.Response;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.HttpHeaders;
import other.entity.Order;
import other.repository.OrderOtherRepository;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class OrderOtherServiceImplF12Test {

    @Mock
    private OrderOtherRepository orderOtherRepository;

    @Mock
    private FeatureFlagService featureFlagService;

    @InjectMocks
    private OrderOtherServiceImpl orderOtherService;

    private static Order order(String from, String to, int status) {
        Order o = new Order();
        o.setId("order-1");
        o.setFrom(from);
        o.setTo(to);
        o.setStatus(status);
        return o;
    }

    private Response save(boolean flag, String from, String to, int newStatus) {
        when(featureFlagService.isEnabled("tt-feat-12")).thenReturn(flag);
        when(orderOtherRepository.findById("order-1"))
                .thenReturn(Optional.of(order(from, to, OrderStatus.PAID.getCode())));
        return orderOtherService.saveChanges(order(from, to, newStatus), new HttpHeaders());
    }

    @Test
    void flagOffCancelsOrderFromLockedStation() {
        Response r = save(false, "Shang Hai", "Nan Jing", OrderStatus.CANCEL.getCode());
        assertEquals(1, r.getStatus().intValue());
        verify(orderOtherRepository).save(any(Order.class));
    }

    @ParameterizedTest
    @ValueSource(strings = {"Shang Hai", "shanghai", "SHANGHAI", "Nan Jing"})
    void flagOnRejectsCancelFromLockedStation(String from) {
        Response r = save(true, from, "Su Zhou", OrderStatus.CANCEL.getCode());
        assertEquals(0, r.getStatus().intValue());
        assertEquals("Order cancel rejected: station locked", r.getMsg());
        verify(orderOtherRepository, never()).save(any(Order.class));
    }

    @Test
    void flagOnRejectsCancelToLockedStation() {
        Response r = save(true, "Su Zhou", "nanjing", OrderStatus.CANCEL.getCode());
        assertEquals(0, r.getStatus().intValue());
    }

    @Test
    void flagOnAllowsCancelBetweenUnlockedStations() {
        Response r = save(true, "Su Zhou", "Wu Xi", OrderStatus.CANCEL.getCode());
        assertEquals(1, r.getStatus().intValue());
    }

    @Test
    void flagOnAllowsNonCancelChangeAtLockedStation() {
        Response r = save(true, "Shang Hai", "Nan Jing", OrderStatus.CHANGE.getCode());
        assertEquals(1, r.getStatus().intValue());
    }
}

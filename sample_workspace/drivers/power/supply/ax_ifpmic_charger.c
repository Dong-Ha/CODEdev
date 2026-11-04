/* SPDX-License-Identifier: GPL-2.0 */
/* AX Code-Dev GUI sample only; NOT a production kernel driver. */

#include <linux/errno.h>
#include <linux/types.h>

#define AX_IFPMIC_INPUT_MAX_MA 3000

struct ax_ifpmic_charger {
    int input_current_ma;
    bool initialized;
};

int ax_ifpmic_set_input_current(struct ax_ifpmic_charger *chip, int current_ma)
{
    if (!chip || !chip->initialized)
        return -ENODEV;

    chip->input_current_ma = current_ma;
    return 0;
}

int ax_ifpmic_get_input_current(const struct ax_ifpmic_charger *chip)
{
    if (!chip || !chip->initialized)
        return -ENODEV;

    return chip->input_current_ma;
}
